from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
from collections import defaultdict
import re
import spacy
import dateparser
import networkx as nx
from model import Task
from hyperon import MeTTa

app = FastAPI()
templates = Jinja2Templates(directory="templates")
nlp = spacy.load("en_core_web_sm")
metta = MeTTa()

tasks = []
task_counter = 1

# Initialize metta knowledge base (classify_task facts)
for word, category in [
    ("alarm", "personal"), ("appointment", "personal"), ("art", "personal"), 
    # ... (your full list here, shortened for brevity)
    ("workflow", "professional"),
]:
    metta.run(f"(classify_task {word} {category})")

def classify_task(task_name: str) -> str:
    words = task_name.lower().split()
    for word in words:
        for category in ["professional", "personal"]:
            result = metta.run(f"! (match &self (classify_task {word} {category}) (x))")
            if result and result != [[]]:
                return category
    return "unknown"

def normalize_date_in_text(text: str) -> str:
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    text = re.sub(r'\btoday\b', today.strftime('%Y-%m-%d'), text, flags=re.I)
    text = re.sub(r'\btomorrow\b', tomorrow.strftime('%Y-%m-%d'), text, flags=re.I)
    date_pattern = re.compile(r'(\b\d{1,2})[-/](\d{1,2})[-/](\d{4}\b)')
    return date_pattern.sub(lambda m: f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}", text)

def parse_task(text: str):
    global task_counter
    normalized_text = normalize_date_in_text(text)
    doc = nlp(normalized_text)

    date_match = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', normalized_text)
    time_match = re.search(r'(\d{1,2}(:\d{2})?\s*(am|pm))', normalized_text, re.I)

    if not date_match:
        return {"error": "missing_date", "original_text": text}
    if not time_match:
        return {"error": "missing_time", "original_text": text}

    dt = dateparser.parse(f"{date_match.group(1)} {time_match.group(1)}")
    if not dt or dt.date() < datetime.now().date():
        return {"error": "invalid_date", "original_text": text}

    duration = 60
    duration_match = re.search(r'(\d+)\s*(hr|hour|hrs|hours|minute|minutes|min|mins)', normalized_text, re.I)
    if duration_match:
        value = int(duration_match.group(1))
        unit = duration_match.group(2).lower()
        duration = value * 60 if 'hour' in unit else value

    task_name = re.split(r'\bon\b|\bat\b|\bfor\b|\bbefore\b|\bafter\b', normalized_text, flags=re.I)[0].strip()
    task_type = classify_task(task_name)
    priority = 1 if task_type == "professional" else 2 if task_type == "personal" else 3

    return Task(
        t_id=task_counter,
        t_name=task_name,
        t_description=text,
        t_priority=priority,
        t_deadline=dt.strftime("%Y-%m-%d"),
        t_duration=duration,
        t_status="pending"
    )

def generate_dependencies_and_schedule():
    dependencies = {}
    grouped = defaultdict(list)

    # Group tasks by deadline date
    for task in tasks:
        dt = datetime.strptime(task.t_deadline, "%Y-%m-%d")
        grouped[dt].append(task)

    sorted_deadlines = sorted(grouped.keys())

    for i, deadline in enumerate(sorted_deadlines):
        task_list = sorted(grouped[deadline], key=lambda t: (t.t_priority, t.t_id))

        # Serial dependencies for same day
        for x in range(len(task_list)):
            for y in range(x + 1, len(task_list)):
                dependencies.setdefault(task_list[y].t_id, []).append(task_list[x].t_id)

        # Next day tasks depend on current day tasks
        if i + 1 < len(sorted_deadlines):
            next_tasks = grouped[sorted_deadlines[i + 1]]
            for src in task_list:
                for tgt in next_tasks:
                    dependencies.setdefault(tgt.t_id, []).append(src.t_id)

    for task in tasks:
        task.t_dependencies = dependencies.get(task.t_id, [])

    G = nx.DiGraph()
    for task in tasks:
        G.add_node(task.t_id, task=task)
        for dep in task.t_dependencies:
            G.add_edge(dep, task.t_id)

    try:
        topo_order = list(nx.topological_sort(G))
    except nx.NetworkXUnfeasible:
        print("Cyclic dependencies detected!")
        return

    work_start = datetime.combine(datetime.today(), datetime.strptime("09:00", "%H:%M").time())
    work_end = datetime.combine(datetime.today(), datetime.strptime("17:00", "%H:%M").time())

    current_time = work_start
    for task_id in topo_order:
        task = G.nodes[task_id]["task"]

        if current_time + timedelta(minutes=task.t_duration) > work_end:
            current_time = current_time.replace(hour=9, minute=0) + timedelta(days=1)

        task.t_start_time = current_time.strftime("%Y-%m-%d %H:%M")
        current_time += timedelta(minutes=task.t_duration)
        task.t_end_time = current_time.strftime("%Y-%m-%d %H:%M")

def clean_task_name(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '', text)
    text = re.sub(r'\b\d{1,2}(:\d{2})?\s*(am|pm)?\b', '', text)
    text = re.sub(r'\b(of|for|on|at|before|after|in|the|a|an)\b', '', text)
    return re.sub(r'\s+', ' ', text).strip()

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    completed = sum(1 for t in tasks if t.t_status == "done")
    total = len(tasks)
    percent = int((completed / total) * 100) if total else 0
    return templates.TemplateResponse("index.html", {"request": request, "tasks": tasks, "completed_percent": percent})

@app.post("/create-task")
async def create_task(request: Request, text: str = Form(...)):
    global task_counter
    result = parse_task(text)

    if isinstance(result, dict) and "error" in result:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "tasks": tasks,
            "completed_percent": int((sum(1 for t in tasks if t.t_status == "done") / len(tasks) * 100)) if tasks else 0,
            "missing_info": result["error"],
            "original_text": result["original_text"]
        })

    new_task = result
    for t in tasks:
        if t.t_name == new_task.t_name and t.t_deadline == new_task.t_deadline:
            return templates.TemplateResponse("index.html", {
                "request": request,
                "tasks": tasks,
                "completed_percent": int((sum(1 for t in tasks if t.t_status == "done") / len(tasks) * 100)) if tasks else 0,
                "missing_info": "duplicate_task",
                "original_text": text
            })

    tasks.append(new_task)
    task_counter += 1
    generate_dependencies_and_schedule()
    return RedirectResponse("/", status_code=303)



@app.post("/complete-task")
def complete_task(t_id: int = Form(...)):
    for t in tasks:
        if t.t_id == t_id:
            t.t_status = "done"
    return RedirectResponse("/", status_code=303)

@app.post("/delete-task")
def delete_task(t_id: int = Form(...)):
    global tasks
    tasks = [t for t in tasks if t.t_id != t_id]
    generate_dependencies_and_schedule()
    return RedirectResponse("/", status_code=303)

@app.get("/graph-data")
def graph_data():
    elements = []
    for t in tasks:
        elements.append({
            "data": {
                "id": str(t.t_id),
                "label": t.t_name,
                "name": clean_task_name(t.t_name),
                "priority": t.t_priority,
                "status": t.t_status
            }
        })
        for dep in getattr(t, 't_dependencies', []):
            elements.append({
                "data": {"source": str(dep), "target": str(t.t_id)}
            })
    return JSONResponse({"elements": elements})
