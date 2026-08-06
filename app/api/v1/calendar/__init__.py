from flask_smorest import Blueprint

from .ApiCalendar import blp as calendar_blueprint
from .ApiSchedulingPolls import blp as scheduling_polls_blueprint
from .ApiAppointmentSlots import blp as appointment_slots_blueprint
from .ApiTeamCalendar import blp as team_calendar_blueprint

calendar_apis: list[Blueprint] = [
    calendar_blueprint,
    scheduling_polls_blueprint,
    appointment_slots_blueprint,
    team_calendar_blueprint,
]
