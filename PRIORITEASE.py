
from datetime import date, datetime, timedelta
import builtins
from contextlib import contextmanager
import os
import re
import sys
import time


APP_NAME = "PrioritEase"

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
STUDENT_LOGIN_MAX_ATTEMPTS = 3
STUDENT_LOGIN_COOLDOWN_SECONDS = 300

# A small local list of obvious weak passwords; long passphrases are encouraged.
COMMON_PASSWORDS = {
    "password", "password1", "12345678", "qwertyui", "qwerty12", "letmein1",
    "abcdefgh", "iloveyou", "passwordpassword", "123456789012345", "12345678901234567890",
    "qwertyqwertyqwerty", "letmeinletmeinletmein", "iloveyouiloveyou",
}

# Students can book up to 14 days ahead, including day 14.
BOOKING_WINDOW_DAYS = 14
FACULTY_CANCELLATION_NOTICE_DAYS = 3
MAX_SLOT_CAPACITY = 50

# Signal used to cancel schedule selection and return to the main menu.
BACK_TO_MAIN_MENU = "back_to_main_menu"

# Return to the faculty menu while keeping the current faculty logged in.
BACK_TO_FACULTY_MENU = "back_to_faculty_menu"

# Return to the student menu without asking for another login.
BACK_TO_STUDENT_MENU = "back_to_student_menu"


# Lower number means higher display priority.
PRIORITY_ORDER = {
    "High": 0,
    "Medium": 1,
    "Normal": 2,
}

# Request statuses belong to each student. Shared slots can be available, full or closed.
STATUS_DESCRIPTIONS = {
    "Pending": "Waiting for the faculty member's decision.",
    "Approved": "Approved; waiting for the consultation or its recorded outcome.",
    "Rejected": "The faculty member rejected the request.",
    "Cancelled": "The faculty member cancelled the approved consultation.",
    "Completed": "The faculty member confirmed that the consultation finished.",
    "No-show": "The faculty member confirmed that the student did not attend.",
    "Expired": "The scheduled time arrived while the request was still pending.",
}

# First-year consultation categories and their base priority scores.
CATEGORY_RULES = [
    ["Missing coursework / incomplete subject requirements", 6],
    ["Missed quizzes or exams / make-up assessments", 5],
    ["Incorrect or missing recorded grades or scores", 4],
    ["Programming exercises / laboratory activity help", 3],
    ["Lesson clarification / assignment feedback", 2],
    ["Study habits / adjustment to college learning", 1],
]

DEFAULT_FACULTY = [
    {
        "id": "F001",
        "password": "prog123",
        "name": "Prof. Gwayne Rithzel Colaste",
        "courses": ["Introduction to Programming 1"],
        "large_capacity_days": (1,),
        "consultation_hours": {
            1: ("08:00", "17:00"),  # Tuesday
            2: ("08:00", "09:00"),  # Wednesday
            3: ("08:00", "09:00"),  # Thursday
        },
    },
    {
        "id": "F002",
        "password": "comp123",
        "name": "Prof. Rachel Joy Piquero",
        "courses": ["Introduction to Computing 1"],
        "large_capacity_days": (2, 4),
        "consultation_hours": {
            2: ("13:30", "16:30"),  # Wednesday
            3: ("08:00", "09:00"),  # Thursday
            4: ("08:30", "11:30"),  # Friday
        },
    },
    {
        "id": "F003",
        "password": "web123",
        "name": "Prof.Xyrus Pogi Urot",
        "courses": ["Web Development", "IT Elective"],
        "large_capacity_days": (2, 4),
        "consultation_hours": {
            2: ("08:30", "12:30"),  # Wednesday
            3: ("08:00", "09:00"),  # Thursday
            4: ("08:30", "11:30"),  # Friday
        },
    },
]
# Sample student accounts.
DEFAULT_STUDENTS = [
    {
        "student_id": "022627009822",
        "name": "Precious Avril Portugal",
        "password": "Precious123"
    },
    {
        "student_id": "022627009987",
        "name": "Nathaniel Erezo",
        "password": "Nathaniel123"
    }
]

# ============================================================
# BASIC CONSOLE FUNCTIONS
# ============================================================
# ============================================================
# KEYBOARD NAVIGATION (STANDARD LIBRARY ONLY)
# ============================================================

DOUBLE_DOWN_SECONDS = 0.6


class GoBack(Exception):
    """Leave the current screen or return to the preceding form step."""


class GoToMainMenu(Exception):
    """Unwind the active session without recreating application data."""


class CancelSteps(Exception):
    """Cancel a form through an existing Enter/numbered cancel option."""


def require_selection(value):
    if value is None:
        raise CancelSteps
    return value


def run_steps(steps):
    """Collect a form one step at a time; never replay a completed action."""
    answers = []
    while len(answers) < len(steps):
        try:
            answer = steps[len(answers)](answers)
        except GoBack:
            if not answers:
                raise
            answers.pop()
        else:
            answers.append(answer)
    return answers


def run_action(action, *args, pause_after=False):
    """Return from a child screen to its caller, keeping the login active."""
    try:
        result = action(*args)
        if pause_after:
            pause()
        return result
    except GoBack:
        return None


def keyboard_shortcuts_available():
    return sys.stdin.isatty() and sys.stdout.isatty()


@contextmanager
def key_reader():
    """Yield a key reader and always restore the terminal on exit."""
    if os.name == "nt":
        import msvcrt

        def read_key():
            character = msvcrt.getwch()
            if character in ("\x00", "\xe0"):
                return {
                    "K": "LEFT", "P": "DOWN", "H": "UP", "M": "RIGHT",
                    "S": "DELETE", "G": "HOME", "O": "END",
                }.get(msvcrt.getwch(), "IGNORE")
            return character

        yield read_key
    else:
        import codecs
        import select
        import termios
        import tty

        descriptor = sys.stdin.fileno()
        previous_settings = termios.tcgetattr(descriptor)
        decoder = codecs.getincrementaldecoder(sys.stdin.encoding or "utf-8")(
            errors="replace"
        )

        def read_character():
            while True:
                raw = os.read(descriptor, 1)
                if not raw:
                    raise EOFError
                character = decoder.decode(raw)
                if character:
                    return character

        def read_key():
            character = read_character()
            if character != "\x1b":
                return character
            sequence = character
            # Read the whole escape sequence so arrow bytes cannot become text.
            while len(sequence) < 32:
                if not select.select([descriptor], [], [], 0.05)[0]:
                    return "IGNORE"
                character = read_character()
                sequence += character
                if len(sequence) == 2 and character not in ("[", "O"):
                    return "IGNORE"
                if len(sequence) > 2 and "@" <= character <= "~":
                    break
            return {
                "\x1b[D": "LEFT", "\x1bOD": "LEFT",
                "\x1b[B": "DOWN", "\x1bOB": "DOWN",
                "\x1b[A": "UP", "\x1bOA": "UP",
                "\x1b[C": "RIGHT", "\x1bOC": "RIGHT",
                "\x1b[3~": "DELETE", "\x1b[H": "HOME",
                "\x1bOH": "HOME", "\x1b[1~": "HOME",
                "\x1b[F": "END", "\x1bOF": "END", "\x1b[4~": "END",
            }.get(sequence, "IGNORE")

        try:
            tty.setcbreak(descriptor, termios.TCSANOW)
            yield read_key
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, previous_settings)


def read_console_line(prompt, read_key, clock=time.monotonic):
    """Read normal text and recognize navigation without requiring Enter."""
    print(prompt, end="", flush=True)
    prompt_line = prompt.rsplit("\n", 1)[-1]
    characters = []
    cursor = 0
    last_down = None
    displayed_length = 0

    while True:
        key = read_key()
        now = clock()
        if key == "LEFT":
            print()
            raise GoBack
        if key == "DOWN":
            if last_down is not None and now - last_down <= DOUBLE_DOWN_SECONDS:
                print()
                raise GoToMainMenu
            last_down = now
            continue

        # Only two consecutive Down presses within the interval count.
        last_down = None
        if key in ("\r", "\n"):
            print()
            return "".join(characters)
        if key == "\x03":
            raise KeyboardInterrupt
        if key in ("\x04", "\x1a") and not characters:
            raise EOFError
        if key in ("\b", "\x7f"):
            if cursor:
                cursor -= 1
                characters.pop(cursor)
        elif key == "DELETE":
            if cursor < len(characters):
                characters.pop(cursor)
        elif key == "RIGHT":
            cursor = min(cursor + 1, len(characters))
        elif key == "HOME":
            cursor = 0
        elif key == "END":
            cursor = len(characters)
        elif len(key) == 1 and key.isprintable():
            characters.insert(cursor, key)
            cursor += 1
        else:
            continue

        text = "".join(characters)
        padding = max(0, displayed_length - len(text))
        sys.stdout.write("\r" + prompt_line + text + " " * padding)
        sys.stdout.write("\b" * (len(text) - cursor + padding))
        sys.stdout.flush()
        displayed_length = len(text)


def console_input(prompt=""):
    if keyboard_shortcuts_available():
        with key_reader() as read_key:
            return read_console_line(prompt, read_key)

    # IDLE, notebooks and redirected input do not expose physical arrow keys.
    value = builtins.input(prompt)
    command = value.strip().lower()
    if command == ":back":
        raise GoBack
    if command == ":main":
        raise GoToMainMenu
    return value



def line(character="=", width=78):
    print(character * width)


def heading(title):
    print()
    line()
    print(title.center(78))
    line()


def pause():
    console_input("\nPress Enter to continue...")


def format_display_datetime(value, include_day=False):
    """Display AM/PM and an optional weekday without changing stored timestamps."""
    formats = (
        ("%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p"),
        ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %I:%M:%S %p"),
    )
    for stored_format, display_format in formats:
        try:
            parsed = datetime.strptime(value, stored_format)
            if include_day:
                display_format = "%A, " + display_format
            return parsed.strftime(display_format)
        except (TypeError, ValueError):
            continue
    return value


def ask_nonempty(prompt):
    while True:
        value = console_input(prompt).strip()
        if value != "":
            return value
        print("Input cannot be empty.")


def ask_consultation_reason(prompt):
    """Require words in the consultation reason and reject any digits."""
    while True:
        reason = ask_nonempty(prompt)

        if any(character.isdigit() for character in reason) or not any(
            character.isalpha() for character in reason
        ):
            print("Please enter a concern/reason using words, without digits.")
            continue

        return reason


def ask_int(prompt, minimum, maximum):
    while True:
        raw = console_input(prompt).strip()

        try:
            value = int(raw)
        except ValueError:
            print("Please enter a valid number.")
            continue

        if minimum <= value <= maximum:
            return value

        print("Please enter a number from", minimum, "to", maximum)


def is_valid_student_id(student_id):
    # Accept 12 ASCII digits, or exactly the 2-4-6 format with hyphens.
    return re.fullmatch(r"(?:[0-9]{12}|[0-9]{2}-[0-9]{4}-[0-9]{6})", student_id) is not None


def normalize_student_id(student_id):
    # Keep leading zeros and use one stored ID for both accepted formats.
    return student_id.replace("-", "")


def ask_student_id(prompt, allow_cancel=False):
    while True:
        student_id = console_input(prompt).strip()

        if allow_cancel and student_id == "":
            return None
        if is_valid_student_id(student_id):
            return normalize_student_id(student_id)

        print("Invalid Student ID. Use 12 digits (0-9), such as 022627010643, or the format 02-2627-010643.")


def get_student(student_id, data):
    for student in data["students"]:
        if student["student_id"] == student_id:
            return student

    return None


def ask_student_name(prompt):
    while True:
        name = " ".join(console_input(prompt).split())
        if name == "":
            return None

        if (
            2 <= len(name) <= 100
            and sum(character.isalpha() for character in name) >= 2
            and name[0].isalpha()
            and (name[-1].isalpha() or name[-1] == ".")
            and all(character.isalpha() or character in " .-'’" for character in name)
        ):
            return name

        print("Invalid name. Use 2-100 characters with letters, spaces, apostrophes, hyphens or periods; no digits or other symbols.")


# ============================================================
# STUDENT PASSWORD VALIDATION
# ============================================================
def is_valid_student_password(password, student_id):
    return (
        PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH
        and password.isprintable()
        and bool(password.strip())
        and password.casefold() not in COMMON_PASSWORDS
        and student_id not in password.replace("-", "")
    )


def ask_new_student_password(student_id):
    print("Create a password with at least 8 characters (maximum 128).")
    print("No special symbols or mix of letters and numbers is required. Press Enter to cancel.")
    while True:
        password = console_input("Create password: ")
        if password == "":
            return None
        if not is_valid_student_password(password, student_id):
            print("Invalid password. Use 8-128 printable characters; avoid blank/common passwords and your Student ID.")
            continue

        try:
            confirmation = console_input("Confirm password: ")
        except GoBack:
            continue
        if confirmation == "":
            return None
        if (
            not PASSWORD_MIN_LENGTH <= len(confirmation) <= PASSWORD_MAX_LENGTH
            or not confirmation.isprintable()
            or password != confirmation
        ):
            print("Passwords do not match. Please create and confirm the password again.")
            continue
        return password


def verify_student_password(student, password):
    if not isinstance(password, str) or not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        return False
    return password == student.get("password")


def authenticate_student(data, student_id, password):
    now = time.monotonic()
    previous = data["student_login_attempts"].get(student_id)
    state = dict(previous) if previous is not None else {"failures": 0, "locked_until": 0.0}
    if state["locked_until"] > 0 and now >= state["locked_until"]:
        state = {"failures": 0, "locked_until": 0.0}

    student = get_student(student_id, data)
    matches = student is not None and verify_student_password(student, password)
    if now < state["locked_until"]:
        return None
    if student is not None and matches:
        data["student_login_attempts"].pop(student_id, None)
        return student

    state["failures"] += 1
    if state["failures"] >= STUDENT_LOGIN_MAX_ATTEMPTS:
        state["locked_until"] = now + STUDENT_LOGIN_COOLDOWN_SECONDS
    data["student_login_attempts"][student_id] = state
    return None


# ============================================================
# STUDENT REGISTRATION
# ============================================================
def register_student(data):
    heading("REGISTER STUDENT")
    print("Provide your Student ID, full name and password. Press Enter at any field to cancel.")

    def choose_new_id(answers):
        while True:
            student_id = require_selection(ask_student_id(
                "Student ID (02-2627-010643 or 022627010643): ", allow_cancel=True
            ))
            if get_student(student_id, data) is None:
                return student_id
            print("This Student ID is already registered. Use Student Menu to log in, or enter a different ID.")

    try:
        student_id, name, password = run_steps([
            choose_new_id,
            lambda answers: require_selection(ask_student_name("Full name: ")),
            lambda answers: require_selection(ask_new_student_password(answers[0])),
        ])
    except CancelSteps:
        print("Registration cancelled. Returning to main menu...")
        return

    # Save only after the whole form has been completed.
    data["students"].append({"student_id": student_id, "name": name, "password": password})
    print("Registration successful. You can now log in through Student Menu using", student_id)


def ask_deadline(prompt):
    while True:
        raw = console_input(prompt).strip()

        if raw == "":
            return None

        try:
            deadline = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            print("Invalid date. Use YYYY-MM-DD, for example 2026-09-30.")
            continue

        if deadline < date.today():
            print("Deadline cannot be in the past.")
            continue

        return deadline


def is_booking_too_early(deadline):
    """Check whether a stated deadline is still outside the booking window."""
    if deadline is None:
        return False

    days_left = (deadline - date.today()).days
    return days_left > BOOKING_WINDOW_DAYS


def short(text, width):
    text = str(text)

    if len(text) <= width:
        return text

    return text[: width - 3] + "..."


def print_table(headers, rows, widths):
    if len(rows) == 0:
        print("No records found.")
        return

    header_parts = []
    for index in range(len(headers)):
        header_parts.append(short(headers[index], widths[index]).ljust(widths[index]))
    print(" | ".join(header_parts))

    separator_parts = []
    for width in widths:
        separator_parts.append("-" * width)
    print("-+-".join(separator_parts))

    for row in rows:
        row_parts = []
        for index in range(len(row)):
            row_parts.append(short(row[index], widths[index]).ljust(widths[index]))
        print(" | ".join(row_parts))

def view_request_details(appointment, data=None):
    heading("CONSULTATION REQUEST DETAILS")

    print("Appointment ID :", appointment["id"])
    print("Student Name   :", appointment["student_name"])
    print("Student ID     :", appointment["student_id"])
    print("Course         :", appointment["course"])
    print("Category       :", appointment["category"])
    print("Reason         :", appointment["reason"])
    print("Deadline       :", appointment["deadline"])
    print("Priority       :", appointment["priority"])
    print("Priority Score :", appointment["priority_score"])
    print("Schedule       :", format_display_datetime(appointment["scheduled_for"], include_day=True))
    print("Status         :", appointment["status"])
    print("Status Meaning :", STATUS_DESCRIPTIONS.get(appointment["status"], ""))
    if appointment.get("status_updated_at"):
        print("Status Updated :", format_display_datetime(appointment["status_updated_at"]))
    print("Submitted Date :", format_display_datetime(appointment["created_at"]))
    if data is not None:
        position = get_queue_position(data, appointment)
        print("Queue Position :", position if position is not None else "Not in active queue")
        slot = get_linked_consultation_slot(data, appointment)
        faculty = get_faculty(data, appointment["faculty_id"])
        if slot is not None and faculty is not None:
            print("Seats Used     :", str(get_slot_occupancy(data, faculty, slot)) + "/" + str(slot["capacity"]))


# ============================================================
# FACULTY CONSULTATION HOURS
# ============================================================
def is_within_faculty_consultation_hours(faculty, slot_datetime):
    """Allow a slot start from opening time up to, but not at, closing time."""
    hours = faculty.get("consultation_hours", {}).get(slot_datetime.weekday())
    if hours is None:
        return False
    start, end = hours
    return start <= slot_datetime.strftime("%H:%M") < end


def show_faculty_consultation_hours(faculty):
    weekdays = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    print("\nFaculty: " + faculty["name"] + " (" + faculty["id"] + ")")
    print("\nWEEKLY CONSULTATION HOURS")
    hours = faculty.get("consultation_hours", {})
    if not hours:
        print("No consultation hours are configured for this faculty member.")
        return
    rows = []
    for weekday, (start, end) in sorted(hours.items()):
        start_text = datetime.strptime(start, "%H:%M").strftime("%I:%M %p").lstrip("0")
        end_text = datetime.strptime(end, "%H:%M").strftime("%I:%M %p").lstrip("0")
        rows.append([weekdays[weekday], start_text, end_text])
    print_table(["Day", "Start Time", "End Time"], rows, [9, 10, 10])


# ============================================================
# DATA STORAGE FUNCTIONS
# ============================================================
def get_slot_capacity_limits(faculty, slot_datetime):
    """Return minimum, maximum and default seats for this consultation day."""
    if slot_datetime.weekday() in faculty.get("large_capacity_days", ()):
        return 20, MAX_SLOT_CAPACITY, 20
    return 1, MAX_SLOT_CAPACITY, 5


def get_slot_appointments(data, faculty, slot):
    """Each request keeps its own identity within the shared schedule."""
    return [
        appointment for appointment in data["appointments"]
        if appointment["faculty_id"] == faculty["id"]
        and appointment["slot_id"] == slot["slot_id"]
        and appointment["scheduled_for"] == slot["datetime"]
    ]


def get_slot_occupancy(data, faculty, slot):
    return sum(
        1 for appointment in get_slot_appointments(data, faculty, slot)
        if appointment["status"] in ("Pending", "Approved", "Completed", "No-show")
    )


def slot_has_protected_requests(data, faculty, slot):
    return any(
        appointment["status"] not in ("Rejected", "Cancelled")
        for appointment in get_slot_appointments(data, faculty, slot)
    )


def refresh_slot_status(data, faculty, slot, now=None):
    current_time = datetime.now() if now is None else now
    start = get_consultation_datetime({"scheduled_for": slot.get("datetime")})
    if start is None or start <= current_time:
        slot["status"] = "closed"
        return
    minimum, maximum, default = get_slot_capacity_limits(faculty, start)
    capacity = slot.get("capacity")
    if (
        not is_within_faculty_consultation_hours(faculty, start)
        or type(capacity) is not int
        or not minimum <= capacity <= maximum
    ):
        slot["status"] = "unavailable"
    elif get_slot_occupancy(data, faculty, slot) >= capacity:
        slot["status"] = "full"
    else:
        slot["status"] = "available"


def get_slot_queue(data, faculty, slot):
    requests = [
        appointment for appointment in get_slot_appointments(data, faculty, slot)
        if appointment["status"] in ("Pending", "Approved")
    ]
    return sorted(requests, key=request_sort_key)


def get_queue_position(data, appointment):
    faculty = get_faculty(data, appointment["faculty_id"])
    slot = get_linked_consultation_slot(data, appointment)
    if faculty is None or slot is None:
        return None
    for position, request in enumerate(get_slot_queue(data, faculty, slot), start=1):
        if request["id"] == appointment["id"]:
            return position
    return None


def validate_slot_configuration(faculty, value, capacity, exclude_slot_id=None, occupied=0):
    start = get_consultation_datetime({"scheduled_for": value})
    if start is None or start <= datetime.now():
        return False, "The consultation slot must be in the future."
    if not is_within_faculty_consultation_hours(faculty, start):
        return False, "The slot must be within this faculty member's consultation hours."
    minimum, maximum, default = get_slot_capacity_limits(faculty, start)
    if type(capacity) is not int or not minimum <= capacity <= maximum:
        return False, "Student capacity must be between " + str(minimum) + " and " + str(maximum) + "."
    if capacity < occupied:
        return False, "Capacity cannot be lower than the " + str(occupied) + " occupied seats."
    if any(slot["datetime"] == value and slot["slot_id"] != exclude_slot_id
           for slot in faculty["availability"]):
        return False, "You already have a consultation slot at that date and time."
    return True, ""


def ask_slot_capacity(faculty, value, occupied=0, current_capacity=None):
    print("\nSchedule:", format_display_datetime(value, include_day=True))
    start = datetime.strptime(value, "%Y-%m-%d %H:%M")
    minimum, maximum, default = get_slot_capacity_limits(faculty, start)
    minimum = max(minimum, occupied)
    if minimum > maximum:
        print("This schedule has more bookings than the allowed maximum. Capacity cannot be changed.")
        raise CancelSteps
    if current_capacity is not None and minimum <= current_capacity <= maximum:
        default = current_capacity
    else:
        default = max(default, minimum)
    while True:
        raw = console_input(
            "Student capacity (" + str(minimum) + "-" + str(maximum)
            + ", press Enter for " + str(default) + "): "
        ).strip()
        if raw == "":
            return default
        try:
            capacity = int(raw)
        except ValueError:
            print("Enter a whole number of students.")
            continue
        if minimum <= capacity <= maximum:
            return capacity
        print("Capacity must be between", minimum, "and", maximum,
              "and cannot be below the occupied seats.")


def reserve_consultation_request(data, student_id, student_name, faculty, course,
                                 category_index, reason, deadline, selected_slot):
    """Recheck and reserve one seat, then assign this student's priority."""
    update_expired_consultations(data)
    if not any(slot is selected_slot for slot in faculty["availability"]):
        return None, "The selected consultation schedule does not belong to this faculty member."
    if any(request["student_id"] == student_id
           and request["status"] in ("Pending", "Approved", "Completed", "No-show")
           for request in get_slot_appointments(data, faculty, selected_slot)):
        return None, "You already have a request for this consultation schedule."
    if not any(slot is selected_slot for slot in get_available_slots(data, faculty)):
        return None, "This schedule is full or no longer available. Please choose another schedule."
    score, priority, days_left = calculate_priority(category_index, deadline)
    appointment = {
        "id": next_appointment_id(data["appointments"]),
        "student_id": student_id,
        "student_name": student_name,
        "faculty_id": faculty["id"],
        "course": course,
        "category": CATEGORY_RULES[category_index][0],
        "reason": reason,
        "deadline": deadline.isoformat() if deadline is not None else "",
        "days_left_at_request": days_left,
        "priority_score": score,
        "priority": priority,
        "slot_id": selected_slot["slot_id"],
        "scheduled_for": selected_slot["datetime"],
        "status": "Pending",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    data["appointments"].append(appointment)
    refresh_slot_status(data, faculty, selected_slot)
    return appointment, "Consultation request submitted successfully."


def choose_faculty_slot(data, faculty):
    update_expired_consultations(data)
    slots = sorted(faculty["availability"], key=lambda slot: slot["datetime"])
    if not slots:
        print("You have no consultation slots.")
        return None
    rows = [[number, slot["slot_id"], format_display_datetime(slot["datetime"], include_day=True),
             str(get_slot_occupancy(data, faculty, slot)) + "/" + str(slot["capacity"]), slot["status"]]
            for number, slot in enumerate(slots, start=1)]
    print_table(["No.", "Slot ID", "Day, Date and Time", "Used/Limit", "Status"], rows, [4, 8, 30, 10, 11])
    cancel = len(slots) + 1
    print(str(cancel) + ". Cancel")
    choice = ask_int("Select slot (" + str(cancel) + " to cancel): ", 1, cancel)
    return None if choice == cancel else slots[choice - 1]


def view_slot_queue(data, faculty):
    heading("VIEW STUDENTS IN A CONSULTATION SCHEDULE")
    slot = choose_faculty_slot(data, faculty)
    if slot is None:
        return
    queue = get_slot_queue(data, faculty, slot)
    print("\nSlot:", slot["slot_id"], "-", format_display_datetime(slot["datetime"], include_day=True))
    print("Seats used:", get_slot_occupancy(data, faculty, slot), "/", slot["capacity"])
    if not queue:
        print("There are no Pending or Approved students in this schedule's queue.")
        return
    rows = [[number, a["id"], a["student_name"], a["student_id"], a["priority"],
             a["priority_score"], a["status"]] for number, a in enumerate(queue, start=1)]
    print_table(["Queue", "ID", "Student", "Student ID", "Priority", "Score", "Status"],
                rows, [5, 8, 24, 12, 8, 5, 10])
    print("High priority comes first, then Medium, then Normal. Earlier submissions break ties.")


def create_default_data():
    faculty_list = []
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for source in DEFAULT_FACULTY:

        faculty = {
            "id": source["id"],
            "password": source["password"],
            "name": source["name"],
            "courses": list(source["courses"]),
            "consultation_hours": dict(source["consultation_hours"]),
            "large_capacity_days": tuple(source["large_capacity_days"]),
            "availability": [],
        }

        # Seed one opening-time slot on each of the next three consultation days.
        for day_offset in range(1, BOOKING_WINDOW_DAYS + 1):
            slot_datetime = today + timedelta(days=day_offset)
            hours = faculty["consultation_hours"].get(slot_datetime.weekday())
            if hours is None:
                continue
            hour, minute = map(int, hours[0].split(":"))
            slot_datetime = slot_datetime.replace(hour=hour, minute=minute)

            faculty["availability"].append(
                {
                    "slot_id": "S" + str(len(faculty["availability"]) + 1).zfill(4),
                    "datetime": slot_datetime.strftime("%Y-%m-%d %H:%M"),
                    "status": "available",
                    "capacity": get_slot_capacity_limits(faculty, slot_datetime)[2],
                }
            )

            if len(faculty["availability"]) == 3:
                break

        faculty_list.append(faculty)

    return {
        "students": [dict(student) for student in DEFAULT_STUDENTS],
        "student_login_attempts": {},
        "faculty": faculty_list,
        "appointments": [],
    }

def next_appointment_id(appointments):
    highest_number = 0

    for appointment in appointments:
        appointment_id = str(appointment.get("id", ""))

        if appointment_id.startswith("A"):
            number_text = appointment_id[1:]

            if number_text.isdigit():
                number = int(number_text)
                if number > highest_number:
                    highest_number = number

    return "A" + str(highest_number + 1).zfill(4)


# ============================================================
# LOOKUP FUNCTIONS
# ============================================================
def get_faculty(data, faculty_id):
    for faculty in data["faculty"]:
        if faculty["id"].lower() == faculty_id.lower():
            return faculty

    return None


def get_appointment(data, appointment_id):
    for appointment in data["appointments"]:
        if appointment["id"].lower() == appointment_id.lower():
            return appointment

    return None

def get_faculty_name(data, faculty_id):
    faculty = get_faculty(data, faculty_id)

    if faculty is None:
        return faculty_id

    return faculty["name"]


# ============================================================
# CONSULTATION LIFECYCLE: EXPIRED, COMPLETED AND NO-SHOW
# ============================================================

def get_consultation_datetime(appointment):
    """Return the scheduled start time, or None for an invalid old record."""
    try:
        return datetime.strptime(appointment.get("scheduled_for", ""), "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def get_linked_consultation_slot(data, appointment):
    """Locate the shared slot without treating one request as its only owner."""
    faculty = get_faculty(data, appointment.get("faculty_id", ""))
    if faculty is None:
        return None
    for slot in faculty["availability"]:
        if (slot["slot_id"] == appointment.get("slot_id")
                and slot["datetime"] == appointment.get("scheduled_for")):
            return slot
    return None


def update_expired_consultations(data, now=None):
    """Expire each elapsed Pending request and refresh shared slot counts."""
    current_time = datetime.now() if now is None else now
    expired_count = 0
    for appointment in data["appointments"]:
        if appointment.get("status") != "Pending":
            continue
        scheduled_time = get_consultation_datetime(appointment)
        if scheduled_time is not None and scheduled_time <= current_time:
            appointment["status"] = "Expired"
            appointment["status_updated_at"] = current_time.strftime("%Y-%m-%d %H:%M:%S")
            expired_count += 1
    for faculty in data["faculty"]:
        for slot in faculty["availability"]:
            refresh_slot_status(data, faculty, slot, current_time)
    return expired_count


def record_consultation_outcome(data, faculty, appointment_id, outcome, now=None):
    if outcome not in ("Completed", "No-show"):
        return False, "Choose Completed or No-show as the consultation outcome."
    current_time = datetime.now() if now is None else now
    update_expired_consultations(data, current_time)
    appointment = get_appointment(data, appointment_id)
    if appointment is None or appointment["faculty_id"] != faculty["id"]:
        return False, "Appointment not found for this faculty member."
    if appointment["status"] != "Approved":
        return False, "Only approved consultations can be marked Completed or No-show."
    start = get_consultation_datetime(appointment)
    if start is None:
        return False, "Cannot update this consultation because its schedule is invalid."
    if start > current_time:
        return False, "The scheduled consultation time has not arrived yet."
    slot = get_linked_consultation_slot(data, appointment)
    if slot is None:
        return False, "Cannot update this consultation because its booking slot does not match."
    appointment["status"] = outcome
    appointment["status_updated_at"] = current_time.strftime("%Y-%m-%d %H:%M:%S")
    refresh_slot_status(data, faculty, slot, current_time)
    return True, "Consultation marked " + outcome + "."


def mark_consultation_outcome(data, faculty):
    def select_request(answers):
        heading("MARK CONSULTATION AS COMPLETED OR NO-SHOW")
        print("Only approved consultations whose scheduled time has arrived can be updated.")
        print("Mark Completed only after the consultation has actually finished.")
        print("Mark No-show only after confirming that the student did not attend.")
        current_time = datetime.now()
        update_expired_consultations(data, current_time)

        eligible_requests = []
        for appointment in get_faculty_requests(data, faculty["id"]):
            scheduled_time = get_consultation_datetime(appointment)
            if (
                appointment["status"] == "Approved"
                and scheduled_time is not None
                and scheduled_time <= current_time
            ):
                eligible_requests.append(appointment)

        if not eligible_requests:
            print("No approved consultations are ready for an outcome update.")
            raise CancelSteps

        rows = [
            [appointment["id"], appointment["student_name"],
             format_display_datetime(appointment["scheduled_for"], include_day=True), appointment["status"]]
            for appointment in eligible_requests
        ]
        print_table(["ID", "Student", "Schedule", "Status"], rows, [8, 25, 30, 10])

        appointment_id = console_input("\nEnter Appointment ID (or press Enter to go back to the faculty menu): ").strip()
        if appointment_id == "":
            raise CancelSteps

        appointment = next(
            (item for item in eligible_requests if item["id"].lower() == appointment_id.lower()),
            None,
        )
        if appointment is None:
            print("Select an eligible consultation from the list above.")
            raise CancelSteps

        return appointment

    def choose_outcome(answers):
        view_request_details(answers[0], data)
        print("\n1. Completed - the consultation finished")
        print("2. No-show - the student did not attend")
        print("3. Back to faculty menu")
        decision = ask_int("Choose the consultation outcome: ", 1, 3)
        if decision == 3:
            raise CancelSteps
        return "Completed" if decision == 1 else "No-show"

    def confirm_outcome(answers):
        print("Mark", answers[0]["id"], "as", answers[1] + "?")
        return ask_int("Enter 1 to confirm, or 2 to go back: ", 1, 2)

    try:
        appointment, outcome, confirmation = run_steps([
            select_request, choose_outcome, confirm_outcome,
        ])
    except CancelSteps:
        return BACK_TO_FACULTY_MENU
    if confirmation == 2:
        return BACK_TO_FACULTY_MENU

    # Revalidate after confirmation, then apply the outcome exactly once.
    success, message = record_consultation_outcome(data, faculty, appointment["id"], outcome)
    print(message)


# ============================================================
# CORE FEATURE: PRIORITY ASSIGNMENT
# ============================================================
def calculate_priority(category_index, deadline):
    category_score = CATEGORY_RULES[category_index][1]
    deadline_score = 0
    days_left = None

    if deadline is not None:
        days_left = (deadline - date.today()).days

        if days_left <= 1:
            deadline_score = 5
        elif days_left <= 3:
            deadline_score = 4
        elif days_left <= 7:
            deadline_score = 3
        elif days_left <= 14:
            deadline_score = 2
        else:
            deadline_score = 1

    total_score = category_score + deadline_score

    if total_score >= 8:
        priority = "High"
    elif total_score >= 4:
        priority = "Medium"
    else:
        priority = "Normal"

    return total_score, priority, days_left


# ============================================================
# CORE FEATURE: SELECT FACULTY
# ============================================================
def choose_faculty(data):
    print("\nAvailable Faculty:")

    rows = []
    number = 1

    for faculty in data["faculty"]:
        courses_text = ", ".join(faculty["courses"])
        rows.append([number, faculty["id"], faculty["name"], courses_text])
        number += 1

    # Widen the Faculty column to fit every instructor's full name.
    faculty_width = max([24] + [len(row[2]) for row in rows])
    print_table(
        ["No.", "ID", "Faculty", "Courses"],
        rows,
        [4, 6, faculty_width, 36],
    )

    choice = ask_int("Select faculty number: ", 1, len(data["faculty"]))
    return data["faculty"][choice - 1]


# ============================================================
# SUPPORTING INPUT: SELECT COURSE / SUBJECT
# ============================================================
def choose_course(faculty):
    while True:
        print("\nCourses / Subjects:")
        for number, course in enumerate(faculty["courses"], start=1):
            print(str(number) + ". " + course)
        other_number = len(faculty["courses"]) + 1
        print(str(other_number) + ". Other / General")
        choice = ask_int("Select course/subject: ", 1, other_number)
        if choice <= len(faculty["courses"]):
            return faculty["courses"][choice - 1]
        try:
            return ask_nonempty("Enter course/subject: ")
        except GoBack:
            continue


# ============================================================
# CORE FEATURE: ENTER CONSULTATION CATEGORY / REASON
# ============================================================
def choose_category():
    print("\nConsultation Categories:")

    number = 1
    for category in CATEGORY_RULES:
        print(str(number) + ". " + category[0])
        number += 1

    choice = ask_int("Select category: ", 1, len(CATEGORY_RULES))
    return choice - 1


# ============================================================
# CORE FEATURE: CHOOSE AVAILABLE CONSULTATION SCHEDULE
# ============================================================
def get_available_slots(data, faculty):
    update_expired_consultations(data)
    last_booking_date = (date.today() + timedelta(days=BOOKING_WINDOW_DAYS)).isoformat()
    return sorted([
        slot for slot in faculty["availability"]
        if slot["status"] == "available" and slot["datetime"][:10] <= last_booking_date
    ], key=lambda slot: slot["datetime"])


def choose_available_slot(data, faculty):
    slots = get_available_slots(data, faculty)
    if not slots:
        print("\nThis faculty member has no consultation seats available within the next",
              BOOKING_WINDOW_DAYS, "days.")
        return None
    print("\nAvailable Consultation Schedules:")
    rows = []
    for number, slot in enumerate(slots, start=1):
        occupied = get_slot_occupancy(data, faculty, slot)
        rows.append([number, slot["slot_id"], format_display_datetime(slot["datetime"], include_day=True),
                     str(occupied) + "/" + str(slot["capacity"]), slot["capacity"] - occupied])
    print_table(["No.", "Slot ID", "Day, Date and Time", "Used/Limit", "Seats Left"],
                rows, [4, 8, 30, 10, 10])
    back_option = len(slots) + 1
    print("\n" + str(back_option) + ". Back to main menu (cancel request)")
    choice = ask_int("Select schedule (" + str(back_option) + " to go back): ", 1, back_option)
    if choice == back_option:
        print("Consultation request cancelled. Returning to main menu...")
        return BACK_TO_MAIN_MENU
    return slots[choice - 1]


# ============================================================
# CORE FEATURE: STUDENT SUBMITS A CONSULTATION REQUEST
# ============================================================
def submit_consultation_request(data, student_id, student_name):
    update_expired_consultations(data)
    heading("SUBMIT CONSULTATION REQUEST")
    def choose_deadline(answers):
        deadline = ask_deadline("Enter deadline (YYYY-MM-DD, or press Enter if none): ")
        if is_booking_too_early(deadline):
            booking_opens = deadline - timedelta(days=BOOKING_WINDOW_DAYS)
            print("\nConsultation request cannot be submitted yet.")
            print("Booking is allowed when", BOOKING_WINDOW_DAYS,
                  "days or fewer remain before your deadline.")
            print("You can book starting:", booking_opens.isoformat())
            raise CancelSteps
        return deadline
    try:
        faculty, course, category_index, reason, deadline, selected_slot = run_steps([
            lambda answers: choose_faculty(data),
            lambda answers: choose_course(answers[0]),
            lambda answers: choose_category(),
            lambda answers: ask_consultation_reason("Enter consultation concern/reason: "),
            choose_deadline,
            lambda answers: choose_available_slot(data, answers[0]),
        ])
    except CancelSteps:
        return
    if selected_slot == BACK_TO_MAIN_MENU:
        return BACK_TO_MAIN_MENU
    if selected_slot is None:
        return
    appointment, message = reserve_consultation_request(
        data, student_id, student_name, faculty, course, category_index, reason, deadline, selected_slot
    )
    print("\n" + message)
    if appointment is None:
        return
    print("Appointment ID :", appointment["id"])
    print("Faculty        :", faculty["name"])
    print("Schedule       :", format_display_datetime(selected_slot["datetime"], include_day=True))
    print("Priority       :", appointment["priority"])
    print("Priority Score :", appointment["priority_score"])
    print("Queue Position :", get_queue_position(data, appointment))
    print("Seats Left     :", selected_slot["capacity"] - get_slot_occupancy(data, faculty, selected_slot))
    print("Status         : Pending")


# ============================================================
# CORE FEATURE: STUDENT CHECKS REQUEST STATUS
# ============================================================
def check_request_status(data, student_id):
    while True:
        update_expired_consultations(data)
        heading("CHECK REQUEST STATUS")

        student_requests = []

        for appointment in data["appointments"]:
            if appointment["student_id"].lower() == student_id.lower():
                student_requests.append(appointment)

        if len(student_requests) == 0:
            print("No consultation requests found for this Student ID.")
            return

        rows = []

        for appointment in student_requests:
            rows.append(
                [
                    appointment["id"],
                    get_faculty_name(data, appointment["faculty_id"]),
                    format_display_datetime(appointment["scheduled_for"], include_day=True),
                    appointment.get("priority", appointment.get("final_priority", appointment.get("initial_priority", "Normal"))),
                    appointment["status"],
                    get_queue_position(data, appointment) or "-",
                ]
            )

        # Keep full instructor names visible in the student's request list too.
        faculty_width = max([22] + [len(row[1]) for row in rows])
        print_table(
            ["ID", "Faculty", "Schedule", "Priority", "Status", "Queue"],
            rows,
            [8, faculty_width, 30, 9, 10, 5],
        ) 



        choice = console_input("\nEnter Appointment ID to view details (or press Enter to go back to the student menu): ").strip()

        # Keep details current even if the user waited at the appointment prompt.
        update_expired_consultations(data)

        if choice == "":
            return BACK_TO_STUDENT_MENU

        appointment = get_appointment(data, choice)

        if appointment is not None and appointment["student_id"].lower() == student_id.lower():
            view_request_details(appointment, data)
            try:
                pause()
            except GoBack:
                continue
            return BACK_TO_STUDENT_MENU
        else:
            print("Appointment not found.")
            return
    
# ============================================================
# CORE FEATURE: FACULTY VIEWS REQUESTS
# ============================================================
def request_sort_key(appointment):
    priority_value = appointment.get("priority", appointment.get("final_priority", appointment.get("initial_priority", "Normal")))
    priority_number = PRIORITY_ORDER.get(priority_value, 9)
    return priority_number, appointment["scheduled_for"], appointment["created_at"]


def get_faculty_requests(data, faculty_id, pending_only=False):
    update_expired_consultations(data)
    requests = []

    for appointment in data["appointments"]:
        if appointment["faculty_id"] == faculty_id and (
            not pending_only or appointment["status"] == "Pending"
        ):
            requests.append(appointment)

    requests.sort(key=request_sort_key)
    return requests


def get_pending_faculty_requests(data, faculty_id):
    return get_faculty_requests(data, faculty_id, pending_only=True)


def view_faculty_requests(data, faculty, pending_only=False):
    heading("PRIORITIZED CONSULTATION REQUESTS")
    requests = get_faculty_requests(data, faculty["id"], pending_only=pending_only)
    if not requests:
        print("No records found.")
        console_input("\nPress Enter to go back to the faculty menu...")
        return BACK_TO_FACULTY_MENU
    rows = []
    for appointment in requests:
        position = get_queue_position(data, appointment)
        rows.append([
            appointment["id"], appointment["student_name"], appointment["priority"],
            position if position is not None else "-", appointment["slot_id"],
            format_display_datetime(appointment["scheduled_for"], include_day=True), appointment["status"],
        ])
    print_table(["ID", "Student", "Priority", "Queue", "Slot ID", "Schedule", "Status"],
                rows, [8, 22, 8, 5, 8, 30, 10])
    print("Queue positions are ranked within each schedule by priority, then submission time.")
    choice = console_input("\nEnter Appointment ID for details (or press Enter for faculty menu): ").strip()
    update_expired_consultations(data)
    if choice == "":
        return BACK_TO_FACULTY_MENU
    appointment = get_appointment(data, choice)
    if appointment is not None and appointment["faculty_id"] == faculty["id"]:
        view_request_details(appointment, data)
        return appointment
    print("Appointment not found.")
        
# ============================================================
# CORE FEATURE: FACULTY APPROVES OR REJECTS
# ============================================================
def approve_or_reject_request(data, faculty):
    heading("APPROVE OR REJECT REQUEST")
    if not get_pending_faculty_requests(data, faculty["id"]):
        print("There are no pending consultation requests for this faculty member.")
        print("Approved and rejected requests remain in the prioritized request list.")
        return
    def select_request(answers):
        result = view_faculty_requests(data, faculty, pending_only=True)
        if result == BACK_TO_FACULTY_MENU or result is None:
            raise CancelSteps
        if result["faculty_id"] != faculty["id"] or result["status"] != "Pending":
            print("Select an unprocessed request belonging to this faculty member.")
            raise CancelSteps
        return result
    def choose_decision(answers):
        print("\n1. Approve")
        print("2. Reject")
        print("3. Back to faculty menu (decide later)")
        return ask_int("Choose decision: ", 1, 3)
    try:
        appointment, decision = run_steps([select_request, choose_decision])
    except CancelSteps:
        return BACK_TO_FACULTY_MENU
    if decision == 3:
        return BACK_TO_FACULTY_MENU
    update_expired_consultations(data)
    if appointment["status"] != "Pending":
        print("This request is no longer pending. Current status:", appointment["status"])
        return
    slot = get_linked_consultation_slot(data, appointment)
    if slot is None:
        print("The consultation schedule no longer matches this request.")
        return
    if decision == 1:
        appointment["status"] = "Approved"
        print("Consultation request approved. This student's reserved seat is confirmed.")
    else:
        appointment["status"] = "Rejected"
        print("Consultation request rejected. This student's seat is released.")
    appointment["status_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    refresh_slot_status(data, faculty, slot)



# ============================================================
# CORE FEATURE: FACULTY CANCELS AN APPROVED CONSULTATION
# ============================================================
def cancel_faculty_consultation(data, faculty):
    restriction = "Cancellations are not allowed within 3 days (72 hours) of the consultation, or after it has started."
    def select_request(answers):
        heading("CANCEL A CONSULTATION")
        print(restriction)
        requests = [a for a in get_faculty_requests(data, faculty["id"]) if a["status"] == "Approved"]
        if not requests:
            print("No approved consultations found for this faculty member.")
            raise CancelSteps
        rows = [[a["id"], a["student_name"], a["slot_id"], format_display_datetime(a["scheduled_for"], include_day=True)]
                for a in requests]
        print_table(["ID", "Student", "Slot ID", "Schedule"], rows, [8, 25, 8, 30])
        appointment_id = console_input("\nEnter Appointment ID (or press Enter for faculty menu): ").strip()
        if appointment_id == "":
            raise CancelSteps
        appointment = get_appointment(data, appointment_id)
        if appointment is None or appointment["faculty_id"] != faculty["id"]:
            print("Appointment not found.")
            raise CancelSteps
        if appointment["status"] != "Approved":
            print("Only approved consultations can be cancelled.")
            raise CancelSteps
        start = get_consultation_datetime(appointment)
        if start is None:
            print("Cannot cancel this consultation because its schedule is invalid.")
            raise CancelSteps
        if start <= datetime.now() + timedelta(days=FACULTY_CANCELLATION_NOTICE_DAYS):
            print(restriction)
            raise CancelSteps
        slot = get_linked_consultation_slot(data, appointment)
        if slot is None:
            print("Cannot cancel this consultation because its booking slot does not match.")
            raise CancelSteps
        return appointment, slot, start
    def confirm(answers):
        view_request_details(answers[0][0], data)
        print("\n1. Cancel this student's consultation")
        print("2. Back to faculty menu")
        return ask_int("Choose decision: ", 1, 2)
    try:
        selected, decision = run_steps([select_request, confirm])
    except CancelSteps:
        return BACK_TO_FACULTY_MENU
    if decision == 2:
        return BACK_TO_FACULTY_MENU
    appointment, slot, start = selected
    if start <= datetime.now() + timedelta(days=FACULTY_CANCELLATION_NOTICE_DAYS):
        print(restriction)
        return
    if appointment["status"] != "Approved" or get_linked_consultation_slot(data, appointment) is not slot:
        print("This consultation is no longer eligible for cancellation.")
        return
    appointment["status"] = "Cancelled"
    appointment["status_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    refresh_slot_status(data, faculty, slot)
    print("Consultation cancelled. One student's seat is released.")
    print("Seats left:", slot["capacity"] - get_slot_occupancy(data, faculty, slot))


# ============================================================
# OFFICIAL STUDENT MENU
# ============================================================
def student_menu(data):
    heading("STUDENT ACCESS")
    print("Three failed attempts temporarily block this Student ID for 5 minutes.")
    max_attempts = STUDENT_LOGIN_MAX_ATTEMPTS
    attempts = 0

    def enter_student_id(answers):
        return console_input("Student ID (02-2627-010643 or 022627010643): ").strip()

    def enter_password(answers):
        # Preserve the original rule that an invalid ID consumes an attempt.
        if not is_valid_student_id(answers[0]):
            return None
        return console_input("Password: ")

    while attempts < max_attempts:
        student_id, password = run_steps([enter_student_id, enter_password])
        if not is_valid_student_id(student_id):
            print("Invalid Student ID. Use 12 digits (0-9), such as 022627010643, or the format 02-2627-010643.")
        else:
            student_id = normalize_student_id(student_id)
            student = authenticate_student(data, student_id, password)
            if student is not None:
                print("\nLogin successful.")
                print("Welcome,", student["name"])
                student_session(data, student)
                return
            print("Invalid Student ID or password, or login temporarily unavailable.")

        attempts += 1
        remaining = max_attempts - attempts
        if remaining > 0:
            print("Attempts remaining:", remaining)
        else:
            print("\nMaximum login attempts reached.")
            print("Returning to main menu...")
            pause()


def student_session(data, student):
    student_id = student["student_id"]
    student_name = student["name"]
    while True:
        update_expired_consultations(data)
        heading("STUDENT MENU - " + student_name + " (" + student_id + ")")
        print("1. Submit consultation request")
        print("2. Check request status")
        print("3. Back to main menu")

        # Left at this menu returns to the main menu; children keep this login.
        choice = ask_int("Choose an option: ", 1, 3)
        if choice == 1:
            result = run_action(student_request_action, submit_consultation_request,
                                data, student_id, student_name)
            if result == BACK_TO_MAIN_MENU:
                return
        elif choice == 2:
            run_action(student_request_action, check_request_status, data, student_id)
        else:
            return


def student_request_action(action, data, *args):
    result = action(data, *args)
    if result not in (BACK_TO_MAIN_MENU, BACK_TO_STUDENT_MENU):
        pause()
    return result


# ============================================================
# FACULTY MANAGES CONSULTATION SLOTS
# ============================================================
def next_slot_id(data, faculty):
    """Continue this faculty member's sequence, including their past requests."""
    highest_number = 0
    records = list(faculty["availability"])
    records.extend(
        appointment for appointment in data["appointments"]
        if appointment["faculty_id"] == faculty["id"]
    )

    for record in records:
        slot_id = str(record.get("slot_id", ""))
        if slot_id.startswith("S") and slot_id[1:].isdigit():
            highest_number = max(highest_number, int(slot_id[1:]))

    return "S" + str(highest_number + 1).zfill(4)


def ask_slot_datetime(faculty, exclude_slot_id=None):
    show_faculty_consultation_hours(faculty)
    print("Choose a future slot start within these hours, before the closing time.")
    while True:
        raw = console_input("Enter slot date and time (YYYY-MM-DD HH:MM AM/PM, or press Enter to cancel): ").strip()
        if raw == "":
            return None

        slot_datetime = None
        for input_format in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M"):
            try:
                slot_datetime = datetime.strptime(raw.upper(), input_format)
                break
            except ValueError:
                continue
        if slot_datetime is None:
            print("Invalid date or time. Use YYYY-MM-DD HH:MM AM/PM, for example 2026-10-10 02:30 PM.")
            continue

        if slot_datetime <= datetime.now():
            print("The consultation slot must be in the future.")
            continue

        if not is_within_faculty_consultation_hours(faculty, slot_datetime):
            print("Outside consultation hours. Choose an allowed day and time from the schedule above.")
            continue

        value = slot_datetime.strftime("%Y-%m-%d %H:%M")
        duplicate = any(
            slot["datetime"] == value and slot["slot_id"] != exclude_slot_id
            for slot in faculty["availability"]
        )
        if duplicate:
            print("You already have a consultation slot at that date and time.")
            continue

        return value


def choose_editable_faculty_slot(data, faculty, allow_occupied=False):
    slot = choose_faculty_slot(data, faculty)
    if slot is None:
        return None
    start = get_consultation_datetime({"scheduled_for": slot["datetime"]})
    if start is None or start <= datetime.now():
        print("Past or started schedules cannot be edited or deleted.")
        return None
    if not allow_occupied and slot_has_protected_requests(data, faculty, slot):
        print("This schedule has student bookings. Its date/time and deletion are protected.")
        return None
    return slot


def add_faculty_slot(data, faculty):
    try:
        value, capacity = run_steps([
            lambda answers: require_selection(ask_slot_datetime(faculty)),
            lambda answers: ask_slot_capacity(faculty, answers[0]),
        ])
    except CancelSteps:
        return
    valid, message = validate_slot_configuration(faculty, value, capacity)
    if not valid:
        print(message)
        return
    slot = {"slot_id": next_slot_id(data, faculty), "datetime": value,
            "capacity": capacity, "status": "available"}
    faculty["availability"].append(slot)
    print("Consultation slot added:", slot["slot_id"], "-", format_display_datetime(value, include_day=True))
    print("Student capacity:", capacity)


def edit_faculty_slot(data, faculty):
    def choose_change(answers):
        while True:
            print("\n1. Change date/time and student capacity")
            print("2. Change student capacity only")
            print("3. Back to faculty menu")
            choice = ask_int("Choose change: ", 1, 3)
            if choice == 3:
                raise CancelSteps
            if choice == 1 and slot_has_protected_requests(data, faculty, answers[0]):
                print("This schedule has bookings. Choose capacity only to keep student schedules intact.")
                continue
            return choice
    def choose_settings(answers):
        slot, change = answers
        occupied = get_slot_occupancy(data, faculty, slot)
        if change == 2:
            capacity = ask_slot_capacity(faculty, slot["datetime"], occupied, slot["capacity"])
            return slot["datetime"], capacity
        return run_steps([
            lambda entries: require_selection(ask_slot_datetime(faculty, exclude_slot_id=slot["slot_id"])),
            lambda entries: ask_slot_capacity(faculty, entries[0], current_capacity=slot["capacity"]),
        ])
    try:
        slot, change, settings = run_steps([
            lambda answers: require_selection(choose_editable_faculty_slot(data, faculty, allow_occupied=True)),
            choose_change, choose_settings,
        ])
    except CancelSteps:
        return
    value, capacity = settings
    if value != slot["datetime"] and slot_has_protected_requests(data, faculty, slot):
        print("This schedule has bookings. Its date and time cannot change.")
        return
    valid, message = validate_slot_configuration(
        faculty, value, capacity, slot["slot_id"], get_slot_occupancy(data, faculty, slot)
    )
    if not valid:
        print(message)
        return
    slot.update(datetime=value, capacity=capacity)
    refresh_slot_status(data, faculty, slot)
    print("Consultation slot updated:", slot["slot_id"], "-", format_display_datetime(value, include_day=True))
    print("Student capacity:", capacity)


def delete_faculty_slot(data, faculty):
    def confirm_delete(answers):
        slot = answers[0]
        print("Delete slot:", slot["slot_id"], "-", format_display_datetime(slot["datetime"], include_day=True))
        return ask_int("Enter 1 to delete, or 2 to cancel: ", 1, 2)
    try:
        slot, confirmation = run_steps([
            lambda answers: require_selection(choose_editable_faculty_slot(data, faculty)),
            confirm_delete,
        ])
    except CancelSteps:
        return
    if confirmation == 2:
        return
    if slot_has_protected_requests(data, faculty, slot):
        print("This schedule now has student bookings and cannot be deleted.")
        return
    if datetime.strptime(slot["datetime"], "%Y-%m-%d %H:%M") <= datetime.now():
        print("Past or started schedules cannot be deleted.")
        return
    faculty["availability"].remove(slot)
    print("Consultation slot deleted.")


def manage_faculty_slots(data, faculty):
    while True:
        update_expired_consultations(data)
        heading("MANAGE CONSULTATION SLOTS")
        show_faculty_consultation_hours(faculty)
        print("\nCONSULTATION SCHEDULES")
        slots = sorted(faculty["availability"], key=lambda slot: slot["datetime"])
        rows = [[number, slot["slot_id"], format_display_datetime(slot["datetime"], include_day=True),
                 str(get_slot_occupancy(data, faculty, slot)) + "/" + str(slot["capacity"]), slot["status"]]
                for number, slot in enumerate(slots, start=1)]
        print_table(["No.", "Slot ID", "Day, Date and Time", "Used/Limit", "Status"], rows, [4, 8, 30, 10, 11])
        print("\nSLOT OPTIONS")
        print("1. Add consultation slot")
        print("2. Edit consultation slot")
        print("3. Delete consultation slot")
        print("4. View student queue")
        print("5. Back to faculty menu")
        choice = ask_int("Choose an option: ", 1, 5)
        if choice == 5:
            return
        if choice == 1:
            run_action(add_faculty_slot, data, faculty)
        elif choice == 2:
            run_action(edit_faculty_slot, data, faculty)
        elif choice == 3:
            run_action(delete_faculty_slot, data, faculty)
        else:
            run_action(view_slot_queue, data, faculty, pause_after=True)


# ============================================================
# OFFICIAL FACULTY MENU
# ============================================================
def faculty_menu(data):
    heading("FACULTY ACCESS")
    faculty = faculty_login(data)
    if faculty is None:
        return

    while True:
        update_expired_consultations(data)
        heading("FACULTY MENU - " + faculty["name"] + " (" + faculty["id"] + ")")
        print("1. View prioritized consultation requests")
        print("2. Manage consultation slots")
        print("3. Approve or reject a request")
        print("4. Cancel a consultation")
        print("5. Mark consultation as Completed or No-show")
        print("6. Back to main menu")
        choice = ask_int("Choose an option: ", 1, 6)

        if choice == 1:
            while True:
                try:
                    result = view_faculty_requests(data, faculty)
                except GoBack:
                    break
                if result == BACK_TO_FACULTY_MENU:
                    break
                # Left from details returns to this booking list.
                run_action(console_input, "\nPress Enter to go back to the booking list...")
        elif choice == 2:
            run_action(manage_faculty_slots, data, faculty)
        elif choice == 3:
            run_action(faculty_request_action, approve_or_reject_request, data, faculty)
        elif choice == 4:
            run_action(faculty_request_action, cancel_faculty_consultation, data, faculty)
        elif choice == 5:
            run_action(faculty_request_action, mark_consultation_outcome, data, faculty)
        else:
            return


def faculty_request_action(action, data, faculty):
    result = action(data, faculty)
    if result != BACK_TO_FACULTY_MENU:
        pause()

def faculty_login(data):
    max_attempts = 3
    attempts = 0
    while attempts < max_attempts:
        print("\nFACULTY LOGIN")
        faculty_id, password = run_steps([
            lambda answers: console_input("Faculty ID: ").strip(),
            lambda answers: console_input("Password: ").strip(),
        ])
        for faculty in data["faculty"]:
            if faculty["id"] == faculty_id and faculty["password"] == password:
                print("\nLogin successful.")
                print("Welcome,", faculty["name"])
                return faculty
        attempts += 1
        remaining = max_attempts - attempts
        if remaining > 0:
            print("\nInvalid Faculty ID or Password.")
            print("Attempts remaining:", remaining)
        else:
            print("\nMaximum login attempts reached.")
            print("Returning to main menu...")
    return None

# ============================================================
# MAIN PROGRAM
# ============================================================
def main():
    data = create_default_data()

    while True:
        try:
            update_expired_consultations(data)
            heading(APP_NAME + " - Priority Faculty Consultation System")
            print("1. Student Menu")
            print("2. Faculty Menu")
            print("3. Register Student")
            print("4. Exit")
            choice = ask_int("Choose an option: ", 1, 4)
            if choice == 1:
                student_menu(data)
            elif choice == 2:
                faculty_menu(data)
            elif choice == 3:
                register_student(data)
            else:
                print("\nThank you for using PrioritEase.")
                break
        except GoBack:
            # The main menu has no parent screen; Left never exits the program.
            continue
        except GoToMainMenu:
            print("Returning to main menu...")
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nProgram interrupted. Goodbye.")
    except EOFError:
        print("\n\nInput stream closed. Goodbye.")
