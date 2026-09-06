"""Seed a demo evaluation cycle for demonstrations.

Usage:
    python seed_demo.py          # create demo users + an active cycle (idempotent)
    python seed_demo.py --wipe   # remove ALL demo data created by this script

Safe to run against production: it only touches the demo users (all on the
@example.com domain) and the single named demo cycle. It never modifies real
users/cycles, and the app's startup seeders are unaffected.

What it creates:
  * 5 demo users (org chart: one manager + four reports), password "demo1234"
  * one ACTIVE cycle with all N x N assignments (same algorithm as the
    "Activate" button in the admin UI)
  * every evaluation EXCEPT the demo-login user's is pre-filled as `completed`
    with 1-5 ratings + a full transcript, so dashboards/reports look real
  * the demo-login user's (James Chen) assignments stay `pending` so you can
    log in as that user and run a live AI interview in front of an audience

Transcripts follow the real interview structure from interview.py: intro,
scoping questions for peers, one section per question category ending in the
two wrap-up questions, then the Comments and Goals free-text questions. Each
transcript also contains one vague-answer/follow-up-probe exchange so the
demo shows that behaviour. Ratings are scope-gated per relationship the same
way the interview is (peers/reports don't answer manager-specific questions).

Tom Reyes is seeded as a struggling employee — mostly 1-3 ratings from others
with a markedly more generous self-evaluation — so there's a low-performer
report to demo alongside the strong ones.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import random

from dotenv import load_dotenv
load_dotenv()

from database import get_db, fetchone, fetchall
from auth import hash_password
from seed import seed_questions

DEMO_DOMAIN = "example.com"
DEMO_PASSWORD = "demo1234"
CYCLE_NAME = "Q3 2026 Performance Review (Demo)"
ADMIN_EMAIL = "hmis@partnersincareoahu.org"

# The demo user whose outgoing evaluations stay PENDING (for a live demo).
DEMO_LOGIN = "james"

# name, email-local, role, department, manager (email-local or None)
PEOPLE = [
    ("Maria Santos",   "maria",   "manager", "HMIS",     None),
    ("James Chen",     "james",   "staff",   "HMIS",     "maria"),
    ("Aisha Patel",    "aisha",   "staff",   "CES",      "maria"),
    ("Tom Reyes",      "tom",     "staff",   "Finance",  "maria"),
    ("Leilani Kahale", "leilani", "staff",   "Planning", "maria"),
]

# Per-person profile so radar charts aren't flat (higher = stronger).
# Tom is deliberately a low performer so the demo has a struggling-employee
# report to show alongside the strong ones.
PROFILE = {"maria": 5, "james": 4, "aisha": 5, "tom": 2, "leilani": 4}

# Profiles at or below this rate as struggling.
LOW_PERFORMER = 2


def email_for(local: str) -> str:
    return f"{local}@{DEMO_DOMAIN}"


def rel_of(evaluator_id, subject_id, manager_of):
    """Same relationship logic as routes/admin.py cycle_activate."""
    if evaluator_id == subject_id:
        return "self"
    if manager_of.get(subject_id) == evaluator_id:
        return "manager"   # evaluator is the subject's manager
    if manager_of.get(evaluator_id) == subject_id:
        return "report"    # subject is the evaluator's manager (upward feedback)
    return "peer"


def rating_for(evaluator_local, subject_local, qid):
    """Deterministic, believable rating weighted toward the subject's profile."""
    rng = random.Random(f"{evaluator_local}:{subject_local}:{qid}")
    base = PROFILE.get(subject_local, 4)
    if base <= LOW_PERFORMER:
        if evaluator_local == subject_local:
            # A struggling employee who doesn't see it: the self line sits well
            # above every other line on the radar chart.
            return rng.choices([3, 4, 5], weights=[4, 5, 2])[0]
        return rng.choices([1, 2, 3, 4], weights=[3, 6, 4, 1])[0]
    if base >= 5:
        return rng.choices([3, 4, 5], weights=[1, 3, 6])[0]
    return rng.choices([3, 4, 5], weights=[2, 5, 3])[0]


# ---------------------------------------------------------------------------
# Interview content
#
# The transcripts below mirror the real interview structure in interview.py:
# a warm intro, scoping questions for peers, then one section per question
# category, each closing with the two wrap-up questions the system prompt
# defines ("What did X do particularly well in this area?" / "Where could X
# improve in this area?"), then the free-text Comments and Goals questions.
#
# Likert questions themselves produce `RATING:N:v` turns in a real interview,
# which reports filter out of the transcript view — so they're recorded in the
# `responses` table (see rating_for) rather than as conversation turns. That
# keeps every Claude turn here paired with a real answer, the way the rendered
# transcript looks in the app. Every turn also carries the section label the
# live interviewer would declare, so demo reports show section headers.
# ---------------------------------------------------------------------------

# (area key, category label as it appears in the question bank, scope)
AREAS = [
    ("communication", "Communication Skills",                 "general"),
    ("motivation",    "Interest, Motivation & Initiative",    "general"),
    ("teamwork",      "Cooperation & Teamwork",               "general"),
    ("productivity",  "Productivity & Technical Knowledge",   "team"),
    ("attendance",    "Attendance, Punctuality & Dependability", "team"),
    ("judgment",      "Judgment & Decision-Making",           "team"),
]

# users.department -> the dept-specific questions.category it maps to, so the
# transcript's section label matches what the live interviewer would declare.
DEPT_CATEGORY = {"CES": "CES Program", "Finance": "Finance", "HMIS": "HMIS"}

# Scopes each relationship unlocks. In this demo every staff member reports to
# Maria, so peers all confirm they're on the same team during scoping.
SCOPES_FOR_REL = {
    "self":    {"general", "team", "manager"},
    "manager": {"general", "team", "manager"},
    "report":  {"general", "team"},
    "peer":    {"general", "team"},
}

# questions.scope -> the short keys used above.
SCOPE_KEY = {
    "general": "general",
    "team_specific": "team",
    "manager_specific": "manager",
    "dept_specific": "dept",
}

# Third-person observations, used by manager / peer / report evaluations.
# Multiple variants per slot so different evaluators don't repeat each other.
CONTENT = {
    "maria": {
        "communication": {
            "good": ["She rewrote the HMIS onboarding packet last quarter, and the same three questions we used to get from every new provider basically stopped coming in.",
                     "At the July all-staff she walked through the new HUD data standards in a way even the non-HMIS folks followed — I saw people taking notes."],
            "improve": ["Her written updates run long. A two-line summary at the top would help those of us skimming on a phone.",
                        "When she's deep in a data problem she assumes context the rest of us don't have, and it takes a few questions to catch up."],
        },
        "motivation": {
            "good": ["She took the HUD Data Standards update on herself over the summer and had our workflow rebuilt weeks before the deadline.",
                     "She's the one who noticed our exit-destination reporting would break under the new rules, and she started fixing it before anyone asked."],
            "improve": ["She absorbs too much personally instead of handing pieces off — it's a bottleneck and it's hard on her.",
                        "I'd like to see her push development opportunities toward the team rather than always taking the hard problem herself."],
        },
        "teamwork": {
            "good": ["During the CES backlog in August she sat with Aisha for two weekends to clear it. She didn't have to do that.",
                     "She's consistently respectful in disagreements — she'll argue a point hard and then back the decision fully."],
            "improve": ["In bigger meetings the same two or three voices dominate. She could deliberately pull the quieter people in.",
                        "She could share credit more visibly; a lot of the team's wins read as hers from the outside."],
        },
        "productivity": {
            "good": ["Two quarterly HUD submissions in a row have gone in clean, which hasn't happened before.",
                     "Her turnaround on provider data requests is the fastest on the team and the quality doesn't slip."],
            "improve": ["Her own processes aren't documented. A lot of how this department runs lives in her head.",
                        "She still does hands-on cleanup work that should be delegated by now."],
        },
        "attendance": {
            "good": ["Completely dependable. Time off is always flagged weeks ahead and handed over properly.",
                     "She's the person who's there when a submission deadline slips into the evening."],
            "improve": ["She answers email through her own PTO, which sets an expectation the rest of us feel.",
                        "Her calendar is so full that getting time with her sometimes takes a week."],
        },
        "judgment": {
            "good": ["When the deduplication script started producing bad merges she stopped the run rather than pushing it through to hit the date. That was the right call and it cost her a weekend.",
                     "She rescoped the data migration once it was clear the original timeline was fiction, instead of letting it fail slowly."],
            "improve": ["She over-analyzes small reversible decisions — some of those could just be made.",
                        "Occasionally waits for complete information when a good-enough call earlier would serve better."],
        },
        "dept": {
            "good": ["She knows the HMIS database better than anyone here; she's who everything escalates to.",
                     "Her grasp of the Data Dictionary and program manuals is genuinely deep — she cites the actual documentation."],
            "improve": ["Her troubleshooting steps need to be written down. If she were out for a month we'd struggle.",
                        "She could run a short internal training instead of answering the same question one-on-one repeatedly."],
        },
    },
    "james": {
        "communication": {
            "good": ["His ticket updates are clear — providers always know what's happening and what's next.",
                     "He wrote up the data-quality issue for the CoC meeting well enough that non-technical people understood the impact."],
            "improve": ["He holds back in meetings. He usually has the right read and waits to be asked for it.",
                        "He'll answer the exact question asked without volunteering the context that changes the answer."],
        },
        "motivation": {
            "good": ["He volunteered to learn the reporting side and now drafts the monthly APR himself.",
                     "He asked to shadow the HUD submission process this cycle, which nobody suggested to him."],
            "improve": ["He waits for direction on stretch work rather than proposing it. He's ready for more than he asks for.",
                        "Could show more curiosity about the parts of the system he doesn't touch day to day."],
        },
        "teamwork": {
            "good": ["He covered Aisha's provider inbox during her leave without being asked and kept it clean.",
                     "Easy to work with — he shares what he knows instead of holding it."],
            "improve": ["He grinds on problems alone too long before asking. An hour of stuck should be a question.",
                        "Could be more visible cross-team; the CES side doesn't really know what he does."],
        },
        "productivity": {
            "good": ["His data cleanup is accurate — his work almost never comes back with corrections.",
                     "He cleared the duplicate-client queue faster than we'd scoped it for."],
            "improve": ["His throughput dips when he's switching between tickets and project work; batching would help.",
                        "He sometimes polishes work that was already good enough to ship."],
        },
        "attendance": {
            "good": ["On time, reliable, plans absences well ahead.",
                     "If he says a date, it holds."],
            "improve": ["He overcommits and then has to renegotiate deadlines — better to push back up front.",
                        "Could give earlier warning when something is slipping instead of trying to recover it quietly."],
        },
        "judgment": {
            "good": ["He caught a mismatch in the exit-destination data before it went into the quarterly report. That would have been embarrassing.",
                     "He asks the right clarifying question before starting rather than building the wrong thing."],
            "improve": ["He escalates decisions he's entirely capable of making himself.",
                        "Could trust his own read more; he second-guesses conclusions that turn out to be right."],
        },
        "dept": {
            "good": ["Solid grasp of the Data Dictionary, and his troubleshooting has gotten noticeably faster this year.",
                     "His response time to provider data requests is consistently good."],
            "improve": ["Still routes the harder database questions to Maria rather than working them through.",
                        "Could go deeper on the program manuals — he knows the common cases well but not the edges."],
        },
    },
    "aisha": {
        "communication": {
            "good": ["She rewrote our intake workflow docs last spring and it cut onboarding questions from new providers dramatically.",
                     "She runs case conference meetings so that everyone actually gets airtime, which is harder than she makes it look."],
            "improve": ["Her emails get blunt when she's under pressure. The content is right but the tone lands badly.",
                        "She could summarize decisions in writing after meetings — a lot gets agreed verbally and then drifts."],
        },
        "motivation": {
            "good": ["She built the case-conference tracker on her own initiative and now the whole team uses it.",
                     "She flagged the gap in our by-name-list process and proposed the fix in the same conversation."],
            "improve": ["She starts new things before finishing the current ones. Pacing would help.",
                        "Could say no more often — she takes on work that isn't hers because it needs doing."],
        },
        "teamwork": {
            "good": ["She's genuinely respectful with providers even when they're being difficult, which sets the tone for everyone.",
                     "She stepped in to help HMIS during the August backlog without being asked."],
            "improve": ["She could loop the HMIS team in earlier when CES changes affect the data side. We find out late.",
                        "Sometimes solves a shared problem alone when involving others would spread the knowledge."],
        },
        "productivity": {
            "good": ["She handles the highest volume of provider inquiries on the team and quality doesn't drop.",
                     "She facilitated all the CES training sessions this cycle on top of her regular caseload."],
            "improve": ["Her case notes are terse. Anyone picking up her work would need to ask her for context.",
                        "She could push back on volume rather than absorbing it."],
        },
        "attendance": {
            "good": ["Extremely dependable — always gives notice and always hands off cleanly.",
                     "She's never the reason a deadline moves."],
            "improve": ["She answers messages at eleven at night. That's not sustainable and it pressures others.",
                        "Could protect focus time; her day is entirely reactive right now."],
        },
        "judgment": {
            "good": ["She escalated the housing placement conflict fast, and because she did it got resolved instead of festering.",
                     "She reads the Policies and Procedures before making a call rather than going from memory."],
            "improve": ["She sometimes decides quickly when a five-minute consult would produce a better answer.",
                        "Could document the reasoning behind judgment calls so the precedent is reusable."],
        },
        "dept": {
            "good": ["She knows the CES Policies and Procedures cold and applies them consistently, even under pressure from providers.",
                     "Her facilitation of case conferences and training sessions is the strongest on the team."],
            "improve": ["Her training sessions should be turned into reusable material instead of being run live every time.",
                        "Response times slip during high-volume weeks — worth flagging for help earlier."],
        },
    },
    "tom": {
        "communication": {
            "good": ["He's polite in person and gets along with people fine.",
                     "When he does write something up, the tone is professional."],
            "improve": ["Emails go unanswered for days. I followed up three times on the same invoice question in June before I got a reply.",
                        "In the June close meeting he couldn't explain his own variance numbers when the director asked. He'd produced them the week before.",
                        "He doesn't flag problems. We find out about them in reconciliation instead of from him."],
        },
        "motivation": {
            "good": ["He completes the recurring tasks he's been doing for a long time.",
                     "He doesn't complain about the work."],
            "improve": ["He's shown no interest in anything beyond the routine. He declined the coding refresher twice this year.",
                        "He waits to be told. In two cycles I can't point to something he identified and fixed on his own.",
                        "When the allocation schedule changed he didn't ask a single question — he just kept doing it the old way."],
        },
        "teamwork": {
            "good": ["He's respectful with colleagues and not disruptive.",
                     "He'll help if you ask him directly."],
            "improve": ["He doesn't volunteer for anything. When the close ran long in August, two other people absorbed his overflow.",
                        "He's effectively invisible in team problem-solving — present, but not contributing.",
                        "Others have started routing around him, which isn't good for him or for us."],
        },
        "productivity": {
            "good": ["Straightforward check requests are usually fine.",
                     "He gets through the routine volume when it's not complicated."],
            "improve": ["Roughly a third of his AP invoices come back with coding errors. The entire August batch had to be reworked.",
                        "The quality gap against others doing the same job is wide and it hasn't narrowed this cycle.",
                        "Work sits. Invoices that should turn around in two days sit for a week with no status."],
        },
        "attendance": {
            "good": ["He's generally physically present during core hours.",
                     "He does take scheduled leave properly through the system."],
            "improve": ["He's late to the Monday finance huddle most weeks. We've stopped waiting to start.",
                        "Unplanned absences come with little or no notice — the month-end close was delayed twice because of it.",
                        "Deadlines pass without a heads-up. I find out something is late by checking, not by being told."],
        },
        "judgment": {
            "good": ["He'll ask before doing something genuinely irreversible.",
                     "He doesn't take risks with things he knows he doesn't understand."],
            "improve": ["He posted to the wrong grant allocation twice and didn't flag either one. We caught both in reconciliation.",
                        "When something doesn't look right he proceeds anyway rather than stopping to check.",
                        "He applies the same approach regardless of whether it's working."],
        },
        "dept": {
            "good": ["He can navigate the basic AP screens in the accounting system.",
                     "He knows where the recurring vendor records live."],
            "improve": ["He doesn't understand the allocation schedule. Someone walks him through it step by step every single cycle.",
                        "Coding accuracy is the core of this role and it's the weakest part of his work.",
                        "He hasn't built any independent capability in the accounting system this year."],
        },
    },
    "leilani": {
        "communication": {
            "good": ["Her board memo on the CoC funding cycle was clear enough that the committee approved it with no follow-up questions.",
                     "She translates between the program side and the funding side better than anyone here."],
            "improve": ["She under-communicates progress. Work is moving but nobody knows where it stands.",
                        "Her updates come at milestones only — a lightweight weekly note would help."],
        },
        "motivation": {
            "good": ["She proposed the quarterly planning retro and now runs it herself.",
                     "She keeps track of funding opportunities nobody asked her to track."],
            "improve": ["She drops ideas she believes in when they meet resistance. She should push harder.",
                        "Could take more ownership of the long-range roadmap instead of waiting for direction."],
        },
        "teamwork": {
            "good": ["She's the reason cross-team decisions actually get written down and followed up.",
                     "She makes space for other people's input in planning sessions."],
            "improve": ["She could delegate parts of the planning calendar rather than owning all of it.",
                        "Could involve the program teams earlier — they see the plan late."],
        },
        "productivity": {
            "good": ["Her funding calendar has put us ahead of three deadlines this year that we'd normally scramble for.",
                     "The NOFO package came together early and cleanly."],
            "improve": ["Long-range projects stall without a nudge. The strategic plan refresh has been open a while.",
                        "She spreads across too many workstreams to finish any of them quickly."],
        },
        "attendance": {
            "good": ["Very dependable, and she plans absences far enough ahead that they never disrupt anything.",
                     "Reliable on commitments — if it's on her calendar it happens."],
            "improve": ["Meeting-heavy weeks eat her focus time and the deep work slips.",
                        "She could block planning time and defend it."],
        },
        "judgment": {
            "good": ["She caught early that the NOFO timeline wasn't achievable and rescoped, rather than letting us find out in week six.",
                     "She's good at separating the decision that matters from the noise around it."],
            "improve": ["She defers to consensus in cases where she has the better read and should just call it.",
                        "Could make provisional decisions earlier and revise, instead of waiting for agreement."],
        },
        "dept": {"good": [], "improve": []},  # Planning has no dept-specific questions
    },
}

# First-person answers for self-evaluations.
SELF = {
    "maria": {
        "communication": ("I put real work into the onboarding packet rewrite this year, and the drop in repeat questions from providers told me it landed.",
                          "I write too much. I know people skim my updates and I should lead with the conclusion."),
        "motivation": ("I got ahead of the HUD Data Standards change instead of reacting to it, which is the first time we've been early on something like that.",
                       "I take on the hard problem myself out of habit. That's not developing anyone."),
        "teamwork": ("I made myself available during the CES backlog and I think the team knew I wasn't going to let them sink.",
                     "I need to be more deliberate about drawing out the quieter people in meetings."),
        "productivity": ("Two clean HUD submissions in a row is the thing I'm most satisfied with this cycle.",
                         "Almost none of how this department runs is written down, and that's on me."),
        "attendance": ("I'm reliable and I don't think availability has ever been the issue.",
                       "I work through my own time off, and I've seen the team start doing the same. I need to stop."),
        "judgment": ("Stopping the deduplication run rather than shipping bad data was the right call even though it cost us the date.",
                     "I deliberate too long on small things that I could just decide."),
        "dept": ("I know the database deeply and I'm a genuine resource for the team on it.",
                 "That knowledge being concentrated in me is a risk to the organization, not a strength."),
    },
    "james": {
        "communication": ("My written ticket updates are clear and providers tell me they know where things stand.",
                          "I'm quiet in meetings. I have a view and I wait to be asked for it, which isn't useful to anyone."),
        "motivation": ("I asked to take on the monthly APR draft and I've been running it since.",
                       "I wait for stretch work to be offered instead of going after it."),
        "teamwork": ("I covered Aisha's inbox during her leave and kept it in good shape.",
                     "I take too long to ask for help. I'll sit on something for a day when a question would take five minutes."),
        "productivity": ("My cleanup work is accurate — it rarely comes back to me.",
                         "I lose time switching between tickets and project work and I haven't found a good rhythm."),
        "attendance": ("I'm on time and I plan my time off well ahead.",
                       "I say yes to too much and then have to renegotiate, which I should handle up front."),
        "judgment": ("Catching the exit-destination mismatch before it reached the report was a good save.",
                     "I run decisions past Maria that I should just be making."),
        "dept": ("My troubleshooting has gotten substantially faster this year and I lean on the Data Dictionary properly now.",
                 "I still hand the hard database problems to Maria instead of working through them."),
    },
    "aisha": {
        "communication": ("The intake workflow rewrite is the thing I'd point to — provider onboarding questions dropped off sharply after it.",
                          "When I'm under pressure my emails get short and people read that as annoyance."),
        "motivation": ("I built the case-conference tracker because we needed it, and the team adopted it.",
                       "I start things before I've finished other things. It catches up with me."),
        "teamwork": ("I try to make sure everyone gets heard in case conferences, including the providers who are hardest to work with.",
                     "I should bring HMIS in earlier when a CES change affects their data."),
        "productivity": ("I carried the highest inquiry volume on the team this cycle and I don't think quality slipped.",
                         "My case notes are too thin for anyone else to pick up."),
        "attendance": ("I'm dependable and I've never been the reason something missed a date.",
                       "I'm answering messages far too late at night and it's not sustainable."),
        "judgment": ("Escalating the housing placement conflict early was the right instinct and it got resolved.",
                     "I decide fast. Usually that's right, but sometimes I should check first."),
        "dept": ("I know the CES Policies and Procedures thoroughly and apply them consistently.",
                 "My trainings should exist as material rather than me delivering them live every time."),
    },
    # Tom's self-assessment is markedly rosier than everyone else's view of him.
    "tom": {
        "communication": ("I think I communicate fine. I'm not someone who creates conflict with people.",
                          "I could probably get back to emails a bit faster during the busy weeks."),
        "motivation": ("I show up and do the job that's in front of me every day.",
                       "Nothing major comes to mind. I do what's asked of me."),
        "teamwork": ("I get along with everybody here. I've never had a problem with anyone on the team.",
                     "Maybe I could speak up more in meetings, but I don't think it's been an issue."),
        "productivity": ("I get my invoices done. The volume is high and I keep up with it.",
                         "There have been a few coding errors, but the system is confusing and the schedule keeps changing."),
        "attendance": ("I'm here every day and I do my hours.",
                       "I've been a few minutes late to the Monday meeting sometimes, but I don't think it's affected anything."),
        "judgment": ("I don't take risks with things. If I'm not sure, I leave it alone.",
                     "I can't think of anything specific. I'd say my judgment has been sound."),
        "dept": ("I know my way around the accounting system and I handle the AP work.",
                 "The allocation schedule could be explained better — I don't think that's a me problem."),
    },
    "leilani": {
        "communication": ("The board memo on the CoC funding cycle went through with no follow-up questions, which I was pleased with.",
                          "I don't communicate progress often enough. People can't tell whether something is moving."),
        "motivation": ("I started the quarterly planning retro and I've kept it going.",
                       "I let go of ideas too easily when they meet resistance."),
        "teamwork": ("I'm usually the one making sure decisions get captured and followed up.",
                     "I hold onto the whole planning calendar when I should be sharing it out."),
        "productivity": ("The funding calendar has kept us ahead of several deadlines this year.",
                         "The strategic plan refresh has been open too long. I've let it drift."),
        "attendance": ("I'm dependable and I plan around my absences carefully.",
                       "I let meetings crowd out the focus time I need for the longer work."),
        "judgment": ("Rescoping the NOFO timeline early was the right call and saved us a bad month.",
                     "I wait for consensus in situations where I should just make the call."),
        "dept": ("", ""),
    },
}

# Free-text Comments and Goals answers (the `text` and `goal` questions).
CLOSING = {
    "maria":   {"comment": "She's the reason this department functions. My concern is concentration risk, not performance.",
                "growth":  "Delegation and documentation. Both come down to letting go of work she's faster at doing herself.",
                "goal_past": "Rebuilt the HMIS workflow for the new HUD Data Standards and got two quarterly submissions in clean.",
                "goal_next": "Document the core troubleshooting processes and hand two recurring responsibilities to the team."},
    "james":   {"comment": "Quietly one of the most reliable people here. Ready for more than he's currently asking for.",
                "growth":  "Confidence, mainly. He should be making more decisions himself and speaking earlier in meetings.",
                "goal_past": "Took over the monthly APR draft and cut the duplicate-client queue down substantially.",
                "goal_next": "Own the HUD submission end to end with Maria reviewing rather than leading."},
    "aisha":   {"comment": "Exceptional this cycle, but carrying more than is reasonable for one person.",
                "growth":  "Sustainability. She needs to delegate, write things down, and stop working at midnight.",
                "goal_past": "Rewrote the intake workflow documentation and built the case-conference tracker.",
                "goal_next": "Convert the CES training into reusable material and hand off part of the provider inbox."},
    "tom":     {"comment": "Performance is below what the role requires and it hasn't improved over the cycle. Accuracy, responsiveness and timeliness are all concerns, and the team has been absorbing the gap. This needs a structured improvement plan with clear checkpoints rather than another cycle of the same feedback.",
                "growth":  "Coding accuracy first — a third error rate on AP invoices isn't workable. Then responsiveness to email and meeting attendance. He also needs to understand the allocation schedule independently rather than being walked through it each cycle.",
                "goal_past": "Goals from last cycle were to improve coding accuracy and complete the accounting system training. Neither was met; the training was declined twice.",
                "goal_next": "A formal 90-day improvement plan: error rate under 5%, same-day acknowledgement of invoice queries, and completion of the allocation schedule training with a competency check."},
    "leilani": {"comment": "Strong planning work and the funding calendar has genuinely changed how far ahead we operate.",
                "growth":  "Visibility and follow-through on the long-range items. Also pushing her own ideas harder.",
                "goal_past": "Built the funding calendar and delivered the NOFO package ahead of schedule.",
                "goal_next": "Close out the strategic plan refresh and set up a standing progress update for the leadership team."},
}


# Phrase pools so seven consecutive sections don't read identically.
SECTION_OPENERS = ["Let's move on to {label}.", "Next, {label}.",
                   "Now I'd like to ask about {label}.", "Moving on to {label}."]
AFTER_RATINGS = ["Thanks for those ratings.", "Got it, thank you.",
                 "That's helpful — thanks.", "Appreciate that.", "Thank you."]
AFTER_STRENGTH = ["That's helpful, thank you.", "Thanks — that's useful context.",
                  "Good to know.", "Understood, thank you.", "That's really helpful."]
# Vague openers, split by tone: a weak evaluation shouldn't open with praise.
VAGUE_POSITIVE = ["Pretty good overall.", "Good stuff.", "No complaints there.",
                  "That one's a strength.", "Solid there.", "Really good."]
VAGUE_NEUTRAL = ["Honestly, not a lot comes to mind.", "Not really, no.",
                 "Hmm. Not much I can point to.", "That's a tough one.",
                 "I'd have to think about that."]
PROBE_POSITIVE = ("Glad to hear it — can you give me a specific example? "
                  "A project, a moment, or something concrete that made you say that.")
PROBE_NEUTRAL = ("That's fair. Even something small — is there any piece of the work "
                 "where you'd say they're steady, or a time it went well?")


def _pick(variants, rng, fallback=""):
    return rng.choice(variants) if variants else fallback


def transcript_for(evaluator_local, subject_local, subject_name, relationship, subject_dept):
    """Build a full interview transcript mirroring the real question flow.

    Returns (role, content, section) triples. `section` is what the live
    interviewer would declare in the tool's `section` field: "Introduction",
    the exact questions.category label, or "Closing".

    Never emits '__START__' or 'RATING:' turns beyond the opening marker —
    reports filter those, and every Claude turn here has a real answer.
    """
    rng = random.Random(f"transcript:{evaluator_local}:{subject_local}:{relationship}")
    first = subject_name.split()[0]
    is_self = relationship == "self"
    # A struggling subject, judged by someone other than themselves.
    is_low = PROFILE.get(subject_local, 4) <= LOW_PERFORMER and not is_self
    scopes = SCOPES_FOR_REL[relationship]
    content = CONTENT[subject_local]

    turns = []
    section = "Introduction"

    def say(role, text):
        # User turns are tagged with the current `section` too, even though
        # live interviews leave conversation_turns.section NULL for the user
        # role (the report renderer ignores a user turn's section entirely).
        # The tagging exists so test_section_labels_change_only_on_assistant_turns
        # has something to assert against: that a section can only ever
        # advance on an assistant turn, never a user one.
        turns.append((role, text, section))

    say("user", "__START__")

    # --- Intro ---
    if is_self:
        say("assistant",
            f"Hi {first} — I'll be walking you through your self-evaluation for this cycle. "
            f"I'll ask about a few different areas, some as 1-5 ratings and some as open questions. "
            f"There are no wrong answers here; be as candid as you can. Let's get started.")
    else:
        say("assistant",
            f"Thanks for making time for this. I'll be gathering your feedback on {subject_name} for this "
            f"evaluation cycle. I'll ask about a few areas, some as 1-5 ratings and some as open questions. "
            f"Your specific examples are the most useful part, so share what comes to mind.")

    # --- Scoping (peers only, matching the real prompt) ---
    if relationship == "peer":
        say("assistant", f"First, a couple of quick scoping questions. Are you on {first}'s team — do you work with them directly day to day?")
        say("user", "Yes, we're both on Maria's team and we work together regularly.")
        say("assistant", f"Thanks. And are you {first}'s manager?")
        say("user", "No, we're peers.")
        say("assistant", "Perfect — that means I'll cover the general and team-specific questions with you.")

    # --- One section per category ---
    areas = [(k, label) for k, label, scope in AREAS if scope in scopes]
    if subject_dept in DEPT_CATEGORY:
        areas.append(("dept", DEPT_CATEGORY[subject_dept]))

    # Show the vague-answer follow-up probe in one section per transcript.
    probe_area = rng.choice([k for k, _ in areas]) if areas else None

    for key, label in areas:
        slot = content.get(key, {})
        if is_self:
            good, improve = SELF[subject_local].get(key, ("", ""))
        else:
            good = _pick(slot.get("good", []), rng)
            improve = _pick(slot.get("improve", []), rng)
        if not good and not improve:
            continue

        section = label
        say("assistant",
            f"Let's start with {label}." if key == areas[0][0]
            else rng.choice(SECTION_OPENERS).format(label=label))
        say("assistant",
            f"{rng.choice(AFTER_RATINGS)} What did {subject_name} do particularly well in this area?")

        if key == probe_area:
            # Demonstrates RULE 2: a vague answer gets one probe for specifics.
            # A struggling employee's evaluator hedges rather than praises.
            if is_low:
                say("user", rng.choice(VAGUE_NEUTRAL))
                say("assistant", PROBE_NEUTRAL)
            else:
                say("user", rng.choice(VAGUE_POSITIVE))
                say("assistant", PROBE_POSITIVE)
            say("user", good)
        else:
            say("user", good)

        say("assistant",
            f"{rng.choice(AFTER_STRENGTH)} And where could {subject_name} improve in this area?")
        say("user", improve)

    # --- Free-text Comments question (general scope) ---
    closing = CLOSING[subject_local]
    section = "Comments"
    say("assistant", f"Those are all the rated questions. Any additional comments you'd like to add about {subject_name}?")
    say("user", closing["comment"] if not is_self else
        "I'd say it was a solid cycle overall, with a couple of things I want to do differently next time.")

    # --- Manager-scope free text + goals ---
    if "manager" in scopes:
        say("assistant",
            f"Are there areas where {subject_name} could improve outcomes or personal growth — "
            f"including anything we've covered or beyond it?")
        say("user", closing["growth"])
        section = "Goals"
        say("assistant", f"What goals has {subject_name} been working on over the last 12 months?")
        say("user", closing["goal_past"])
        say("assistant", "And what goals should they focus on for the next 12 months?")
        say("user", closing["goal_next"])

    # --- Close ---
    section = "Closing"
    say("assistant",
        "That's everything — thank you for taking the time and for being so specific. "
        "Your responses have been recorded.")
    return turns


def wipe(conn):
    cycle = fetchone(conn, "SELECT id FROM cycles WHERE name = ?", (CYCLE_NAME,))
    if cycle:
        cid = cycle["id"]
        conn.execute(
            "DELETE FROM responses WHERE assignment_id IN "
            "(SELECT id FROM assignments WHERE cycle_id = ?)", (cid,))
        conn.execute(
            "DELETE FROM conversation_turns WHERE assignment_id IN "
            "(SELECT id FROM assignments WHERE cycle_id = ?)", (cid,))
        conn.execute("DELETE FROM assignments WHERE cycle_id = ?", (cid,))
        conn.execute("DELETE FROM cycle_participants WHERE cycle_id = ?", (cid,))
        conn.execute("DELETE FROM cycles WHERE id = ?", (cid,))
        print(f"Deleted demo cycle #{cid} and its assignments/responses/turns.")
    n = conn.execute(
        "DELETE FROM users WHERE email LIKE ?", (f"%@{DEMO_DOMAIN}",)).rowcount
    print(f"Deleted {n} demo user(s) (@{DEMO_DOMAIN}).")


def seed(conn):
    # Ensure the question bank exists (idempotent; prod already has it).
    admin = fetchone(conn, "SELECT id FROM users WHERE lower(email) = ?", (ADMIN_EMAIL,))
    if not admin:
        print(f"WARNING: admin {ADMIN_EMAIL} not found; created_by will be NULL.")
    created_by = admin["id"] if admin else None

    if fetchone(conn, "SELECT 1 FROM cycles WHERE name = ?", (CYCLE_NAME,)):
        print(f"Demo cycle '{CYCLE_NAME}' already exists. "
              f"Run `python seed_demo.py --wipe` first to re-seed. Nothing done.")
        return

    # --- Users (create manager first so manager_id resolves) ---
    ids = {}  # email-local -> user id
    for name, local, role, dept, _mgr in PEOPLE:
        existing = fetchone(conn, "SELECT id FROM users WHERE lower(email) = ?", (email_for(local),))
        if existing:
            ids[local] = existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO users (name,email,password_hash,role,department) VALUES (?,?,?,?,?)",
                (name, email_for(local), hash_password(DEMO_PASSWORD), role, dept))
            ids[local] = cur.lastrowid
    for name, local, role, dept, mgr in PEOPLE:
        if mgr:
            conn.execute("UPDATE users SET manager_id = ? WHERE id = ?", (ids[mgr], ids[local]))
    print(f"Ensured {len(PEOPLE)} demo users (password '{DEMO_PASSWORD}').")

    id_to_local = {v: k for k, v in ids.items()}
    manager_of = {}
    for name, local, role, dept, mgr in PEOPLE:
        manager_of[ids[local]] = ids[mgr] if mgr else None

    # --- Cycle (active) + participants ---
    cur = conn.execute(
        "INSERT INTO cycles (name,description,status,start_date,end_date,created_by) "
        "VALUES (?,?,?,?,?,?)",
        (CYCLE_NAME, "Sample cycle with demo data for demonstration.",
         "active", "2026-07-01", "2026-09-30", created_by))
    cycle_id = cur.lastrowid
    participant_ids = list(ids.values())
    for uid in participant_ids:
        conn.execute("INSERT OR IGNORE INTO cycle_participants (cycle_id,user_id) VALUES (?,?)",
                     (cycle_id, uid))

    # --- Assignments (N x N, same algorithm as cycle_activate) ---
    demo_login_id = ids[DEMO_LOGIN]
    likert_qs = fetchall(
        conn,
        "SELECT id, department, scope FROM questions "
        "WHERE is_active = 1 AND question_type = 'likert'")

    n_completed = n_pending = 0
    for ev in participant_ids:
        for su in participant_ids:
            rel = rel_of(ev, su, manager_of)
            cur = conn.execute(
                "INSERT OR IGNORE INTO assignments "
                "(cycle_id, evaluator_id, subject_id, relationship, status) VALUES (?,?,?,?,?)",
                (cycle_id, ev, su, rel, "pending"))
            aid = cur.lastrowid

            # Leave the demo-login user's OUTGOING evals pending for a live demo.
            if ev == demo_login_id:
                n_pending += 1
                continue

            # Everything else: mark completed with ratings + a short transcript.
            subj_local = id_to_local[su]
            subj_dept = next(d for _n, l, _r, d, _m in PEOPLE if l == subj_local)
            allowed = SCOPES_FOR_REL[rel]
            for q in likert_qs:
                # Mirror interview.py: dept-specific questions apply whenever the
                # subject's department matches; everything else is gated on the
                # scopes this relationship unlocks.
                if q["scope"] == "dept_specific":
                    if q["department"] != subj_dept:
                        continue
                elif SCOPE_KEY.get(q["scope"], "general") not in allowed:
                    continue
                conn.execute(
                    "INSERT INTO responses (assignment_id, question_id, rating) VALUES (?,?,?)",
                    (aid, q["id"], rating_for(id_to_local[ev], subj_local, q["id"])))
            subj_name = next(n for n, l, _r, _d, _m in PEOPLE if l == subj_local)
            for role, content, section in transcript_for(
                    id_to_local[ev], subj_local, subj_name, rel, subj_dept):
                conn.execute(
                    "INSERT INTO conversation_turns (assignment_id, role, content, section) "
                    "VALUES (?,?,?,?)",
                    (aid, role, content, section))
            conn.execute(
                "UPDATE assignments SET status='completed', "
                "started_at=datetime('now','-5 days'), completed_at=datetime('now','-3 days') "
                "WHERE id = ?", (aid,))
            n_completed += 1

    print(f"Created cycle #{cycle_id} '{CYCLE_NAME}' (active) with "
          f"{n_completed} completed + {n_pending} pending assignments.")
    print(f"Live-demo login: {email_for(DEMO_LOGIN)} / {DEMO_PASSWORD} "
          f"({n_pending} pending evaluations to run).")
    print("Populated reports: log in as admin and open any subject's report "
          f"in cycle #{cycle_id} (e.g. Aisha Patel).")


def main():
    wipe_mode = "--wipe" in sys.argv[1:]
    seed_questions()  # ensure question bank exists (idempotent)
    with get_db() as conn:
        if wipe_mode:
            wipe(conn)
        else:
            seed(conn)


if __name__ == "__main__":
    main()
