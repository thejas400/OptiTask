from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
from hyperon import MeTTa
import matplotlib.pyplot as plt
import networkx as nx
from io import BytesIO
from collections import defaultdict

# ---------- Models ----------
from model import Task

# ---------- FastAPI Setup ----------
app = FastAPI()
templates = Jinja2Templates(directory="templates")
tasks = []

# ---------- MeTTa Setup ----------
metta = MeTTa()
metta.run('''
    (classify_task meeting professional)
    (classify_task report professional)
    (classify_task client professional)
    (classify_task project professional)
    (classify_task email professional)
    (classify_task gym personal)
    (classify_task grocery personal)
    (classify_task family personal)
    (classify_task birthday personal)
    (classify_task call_mom personal)
''')

def classify_task(task_name: str) -> str:
    words = task_name.lower().replace("-", " ").replace("_", " ").split()
    for word in words:
        for category in ["professional", "personal"]:
            result = metta.run(f'! (match &self (classify_task {word} {category}) (ddd))')
            if result and result != [[]]:
                return category
    return "unknown"

# ---------- Dependency Logic ----------

def generate_dependencies():
    dependencies = {}
    grouped = defaultdict(list)

    # Group tasks by deadline date (as datetime for sorting)
    for task in tasks:
        dt = datetime.strptime(task.t_deadline, "%Y-%m-%d")
        grouped[dt].append(task)

    # Sort deadlines ascending
    sorted_deadlines = sorted(grouped.keys())

    # For each deadline group, sort tasks by priority and ID
    for i, deadline in enumerate(sorted_deadlines):
        task_list = sorted(grouped[deadline], key=lambda t: (t.t_priority, t.t_id))

        # Link tasks within the same deadline group (like before)
        for x in range(len(task_list)):
            for y in range(x + 1, len(task_list)):
                src = task_list[x]
                tgt = task_list[y]
                dependencies.setdefault(tgt.t_id, []).append(src.t_id)

        # Now link all tasks from this deadline to all tasks in the *next* deadline
        if i + 1 < len(sorted_deadlines):
            next_task_list = sorted(grouped[sorted_deadlines[i + 1]], key=lambda t: (t.t_priority, t.t_id))
            for src in task_list:
                for tgt in next_task_list:
                    dependencies.setdefault(tgt.t_id, []).append(src.t_id)

    # Assign dependencies back to tasks
    for task in tasks:
        task.t_dependencies = dependencies.get(task.t_id, [])

# ---------- Routes ----------
@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "tasks": tasks})

@app.post("/add-task")
def add_task(
    t_id: int = Form(...),
    t_name: str = Form(...),
    t_description: str = Form(...),
    t_deadline: str = Form(...),
    t_duration: int = Form(...)
):
    if t_name.strip().isdigit():
        return HTMLResponse("❌ Task name cannot be just numbers.", status_code=400)

    for task in tasks:
        if task.t_id == t_id:
            return HTMLResponse("❌ Task ID must be unique.", status_code=400)

    try:
        deadline_dt = datetime.strptime(t_deadline, "%Y-%m-%d")
        if deadline_dt < datetime.now():
            return HTMLResponse("❌ Deadline must be in the future.", status_code=400)
    except ValueError:
        return HTMLResponse("❌ Invalid date format.", status_code=400)

    if not (0 < t_duration <= 1440):
        return HTMLResponse("❌ Duration must be between 1 and 1440 minutes.", status_code=400)

    task_type = classify_task(t_name)
    priority = 1 if task_type == "professional" else 2 if task_type == "personal" else 3

    new_task = Task(
        t_id=t_id,
        t_name=t_name,
        t_description=t_description,
        t_priority=priority,
        t_deadline=t_deadline,
        t_duration=t_duration
    )
    tasks.append(new_task)
    generate_dependencies()
    return RedirectResponse(url="/", status_code=303)

@app.get("/dependency-graph")
def dependency_graph():
    G = nx.DiGraph()

    for task in tasks:
        G.add_node(task.t_id, label=task.t_name)
        for dep_id in task.t_dependencies:
            G.add_edge(dep_id, task.t_id)

    # Try topological sort for layout
    try:
        ordered_nodes = list(nx.topological_sort(G))
        pos = nx.spring_layout(G)  # you can also use shell_layout or kamada_kawai_layout
    except nx.NetworkXUnfeasible:
        return HTMLResponse("Cycle detected. Cannot create a valid dependency graph.", status_code=500)

    labels = {node: f"{node}: {G.nodes[node]['label']}" for node in G.nodes}
    plt.figure(figsize=(10, 6))
    nx.draw(G, pos, with_labels=True, labels=labels, node_color='skyblue', node_size=2000,
            font_size=10, font_weight='bold', arrows=True)
    plt.title("Task Dependency Graph")

    buf = BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)
    return StreamingResponse(buf, media_type='image/png')
