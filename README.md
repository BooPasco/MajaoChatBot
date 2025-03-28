Calendar.py

**Purpose**: Handles all calendar operations for Majao Studio—checking availability and booking classes.

#### Inputs & Outputs

1. **availability(start_time, length, style)**
    - **Inputs**:
        - start_time: String (e.g., "15:00"), in 24-hour format.
        - length: Integer (minutes, e.g., 60 for 1 hour).
        - style: String (e.g., "salsa", "bachata").
    - **Rules**:
        - Two classes can overlap if they’re the same style.
        - If the preferred time isn’t free, suggest 2 closest available times that day.
    - **Output**: Dict with:
        - is_free: Boolean (True if preferred time works).
        - start: Datetime (preferred start, or None if not free).
        - end: Datetime (preferred end, or None if not free).
        - suggestions: List of 2 dicts (each with start, end) if not free.
2. **booking(start_time, length, style, student, teacher, student_email, teacher_email, unique_code=None)**
    - **Inputs**:
        - start_time: String (e.g., "15:00").
        - length: Integer (minutes).
        - style: String.
        - student: String (student name).
        - teacher: String (teacher name).
        - student_email: String.
        - teacher_email: String.
        - unique_code: String (optional, auto-generated if None).
    - **Actions**:
        - Books event titled “Student & Teacher: STYLE”.
        - Adds student and teacher emails as guests.
        - Sets location to “Majao Studio Medellin”.
        - Verifies event exists after booking.
    - **Output**: Dict with:
        - success: Boolean (True if booked and verified).
        - event_id: String (Google Calendar event ID).
        - unique_code: String (generated or provided).
