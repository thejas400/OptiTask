class Task:
    def __init__(self, t_id, t_name, t_description, t_priority, t_deadline, t_duration, t_status):
        self.t_id = t_id
        self.t_name = t_name
        self.t_description = t_description
        self.t_priority = t_priority
        self.t_deadline = t_deadline
        self.t_duration = t_duration
        self.t_status = t_status
        self.t_dependencies = []
        self.t_start_time = None
        self.t_end_time = None
