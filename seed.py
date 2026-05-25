"""Seed the question bank from the Annual Evaluation spreadsheet.
Run once: python seed.py
Safe to re-run — skips questions that already exist.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from database import create_tables, get_db

# (category, text, question_type, scope, department, order_index)
QUESTIONS = [
    # --- Section 1: Productivity & Technical Knowledge (team_specific) ---
    ("Productivity & Technical Knowledge",
     "Knows and understands job requirements.",
     "likert", "team_specific", None, 101),
    ("Productivity & Technical Knowledge",
     "Knows how to perform present work effectively.",
     "likert", "team_specific", None, 102),
    ("Productivity & Technical Knowledge",
     "Knows how and where to find answers to job-related technical questions.",
     "likert", "team_specific", None, 103),
    ("Productivity & Technical Knowledge",
     "Quantity and quality of work compare favorably with that of others who have similar production opportunity.",
     "likert", "team_specific", None, 104),
    ("Productivity & Technical Knowledge",
     "Finished product is technically satisfactory.",
     "likert", "team_specific", None, 105),
    ("Productivity & Technical Knowledge",
     "Diligently pursues tasks to completion without unnecessary delay.",
     "likert", "team_specific", None, 106),

    # --- Section 2: Communication Skills (general) ---
    ("Communication Skills",
     "Makes themselves readily understood.",
     "likert", "general", None, 201),
    ("Communication Skills",
     "Expresses thoughts well orally.",
     "likert", "general", None, 202),
    ("Communication Skills",
     "Writes clearly, logically, and concisely.",
     "likert", "general", None, 203),

    # --- Section 3: Interest, Motivation & Initiative (mixed) ---
    ("Interest, Motivation & Initiative",
     "Shows interest in present job responsibilities.",
     "likert", "team_specific", None, 301),
    ("Interest, Motivation & Initiative",
     "Demonstrates interest in work of service.",
     "likert", "general", None, 302),
    ("Interest, Motivation & Initiative",
     "Ambitious and interested in self-development.",
     "likert", "manager_specific", None, 303),
    ("Interest, Motivation & Initiative",
     "Interested in doing a good job.",
     "likert", "general", None, 304),
    ("Interest, Motivation & Initiative",
     "Demonstrates initiative and seeks out additional responsibility.",
     "likert", "team_specific", None, 305),
    ("Interest, Motivation & Initiative",
     "Identifies problems and solutions.",
     "likert", "general", None, 306),
    ("Interest, Motivation & Initiative",
     "Thrives on new challenges and adjusts to unexpected changes.",
     "likert", "team_specific", None, 307),

    # --- Section 4: Attendance, Punctuality & Dependability (team_specific) ---
    ("Attendance, Punctuality & Dependability",
     "Reports to work on time.",
     "likert", "team_specific", None, 401),
    ("Attendance, Punctuality & Dependability",
     "Provides advance notice of need for absence.",
     "likert", "team_specific", None, 402),
    ("Attendance, Punctuality & Dependability",
     "Consistently performs at a high level.",
     "likert", "team_specific", None, 403),
    ("Attendance, Punctuality & Dependability",
     "Manages time and workload effectively to meet responsibilities.",
     "likert", "team_specific", None, 404),

    # --- Section 5: Cooperation & Teamwork (general) ---
    ("Cooperation & Teamwork",
     "Respectful of colleagues when working with others.",
     "likert", "general", None, 501),
    ("Cooperation & Teamwork",
     "Makes valuable contributions to help the group achieve its goals.",
     "likert", "general", None, 502),

    # --- Section 6: Judgment & Decision-Making (team_specific) ---
    ("Judgment & Decision-Making",
     "Makes thoughtful, well-reasoned decisions.",
     "likert", "team_specific", None, 601),
    ("Judgment & Decision-Making",
     "Exercises good judgment, resourcefulness, and creativity in problem-solving.",
     "likert", "team_specific", None, 602),

    # --- Section 7: Comments (mixed) ---
    ("Comments",
     "Additional comments.",
     "text", "general", None, 701),
    ("Comments",
     "Are there areas where this person could improve outcomes or personal growth? "
     "Include any areas covered in this evaluation and beyond.",
     "text", "manager_specific", None, 702),

    # --- Section 8: Goals (manager_specific) ---
    ("Goals",
     "Goals worked on over the last 12 months.",
     "goal", "manager_specific", None, 801),
    ("Goals",
     "Goals for the next 12 months.",
     "goal", "manager_specific", None, 802),

    # --- CES Department-Specific ---
    ("CES Program",
     "Consistently references and follows the CES Policies and Procedures.",
     "likert", "dept_specific", "CES", 901),
    ("CES Program",
     "Does not unnecessarily delay responses to provider inquiries, or asks team for "
     "assistance when there may be a delay due to workload.",
     "likert", "dept_specific", "CES", 902),
    ("CES Program",
     "Efficiently and effectively facilitates all forms of case conference meetings "
     "and CES training sessions.",
     "likert", "dept_specific", "CES", 903),

    # --- Finance Department-Specific ---
    ("Finance",
     "Able to use accurate coding.",
     "likert", "dept_specific", "Finance", 1001),
    ("Finance",
     "Understands allocation schedule.",
     "likert", "dept_specific", "Finance", 1002),
    ("Finance",
     "Able to review AP invoices and create check requests with accuracy.",
     "likert", "dept_specific", "Finance", 1003),
    ("Finance",
     "Understands and navigates through the accounting system.",
     "likert", "dept_specific", "Finance", 1004),

    # --- HMIS Department-Specific ---
    ("HMIS",
     "Shows a robust understanding of the HMIS database and how to troubleshoot "
     "and find solutions to issues.",
     "likert", "dept_specific", "HMIS", 1101),
    ("HMIS",
     "Response time to providers and/or data inquiries and requests are appropriate "
     "and without unnecessary delay.",
     "likert", "dept_specific", "HMIS", 1102),
    ("HMIS",
     "Continues to expand knowledge of HUD HMIS documentation and policies "
     "(Data Standards, Data Dictionary, Program Manuals, etc.).",
     "likert", "dept_specific", "HMIS", 1103),
]


def seed_questions():
    create_tables()
    with get_db() as conn:
        existing = {
            row["text"]
            for row in conn.execute("SELECT text FROM questions").fetchall()
        }
        inserted = 0
        for cat, text, qtype, scope, dept, order in QUESTIONS:
            if text in existing:
                continue
            conn.execute(
                "INSERT INTO questions (category,text,question_type,scope,department,order_index) "
                "VALUES (?,?,?,?,?,?)",
                (cat, text, qtype, scope, dept, order),
            )
            inserted += 1
        print(f"Seeded {inserted} questions ({len(existing)} already existed).")


if __name__ == "__main__":
    seed_questions()
    print("Done.")
