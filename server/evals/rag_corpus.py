"""Synthetic files, email, notes and calendar for the RAG eval, with known answers.

Includes decoys (similar syllabi, a moved deadline) to test precision.
"""

def _file(name, folder, at, text):
    return {"kind": "file", "ref": f"file:/Users/sam/Documents/{folder}/{name}", "title": name, "folder": folder,
            "at": at, "link": f"/Users/sam/Documents/{folder}/{name}", "version": "1", "text": text}


def _email(uid, who, subject, at, text):
    return {"kind": "email", "ref": f"email:{uid}", "title": subject, "who": who, "at": at, "link": "",
            "version": uid, "text": f"From: {who}\nSubject: {subject}\n\n{text}"}


ITEMS = [
    _file("CS589_Syllabus_Fall2026.pdf", "CS589", "2026-09-02T10:00",
          "CS 589: Machine Learning, Fall 2026. Instructor: Prof. Nancy Lee. Lectures Tuesday and Thursday "
          "10:00-11:15 in Goessmann 20.\n\nGrading: homework 40%, midterm 25%, final project 35%.\n\n"
          "Late policy: each student has 3 free late days for the whole semester, to use on homework only. "
          "After that, late homework loses 20% per day. The final project cannot be late.\n\n"
          "Important dates: the midterm exam is on Tuesday, November 4, in class. The final project is due "
          "Friday, December 12 at 5:00 pm, with a short presentation the week before."),
    _file("STAT310_syllabus.pdf", "stat310", "2026-09-03T09:00",
          "STAT 310: Fundamentals of Data Science. Prof. Daniel Ortiz. Homework is due on Fridays at 11:59 pm "
          "on Gradescope. You have 5 late days to use across all homework, at most 2 on any one assignment.\n\n"
          "Office hours: Tuesdays 2:00-3:00 pm in LGRT 1234, or by appointment. The final exam is cumulative."),
    _file("CS305_syllabus.docx", "CS305", "2026-09-01T12:00",
          "CS 305: Social Issues in Computing. Weekly reflection essays are due Sundays at noon. "
          "No late work is accepted in this course, except with a dean's note."),
    _file("Lease_Maple_St_204.pdf", "Housing", "2026-07-20T16:30",
          "Residential lease for 204 Maple Street, Apartment 2B. Landlord: Maria Chen. Tenant: Sam Rivera.\n\n"
          "Rent is $950 per month, due on the 1st of each month. A $50 late fee applies after the 5th.\n\n"
          "Quiet hours are from 10:00 pm to 7:00 am. Trash pickup is on Wednesday mornings. "
          "The lease runs from August 15, 2026 to May 31, 2027."),
    _file("Banana_bread.md", "Recipes", "2026-03-11T19:00",
          "Banana bread: 3 ripe bananas, 1/3 cup melted butter, 3/4 cup sugar, 1 egg, 1 tsp baking soda, "
          "1.5 cups flour. Bake at 350 F for 60 minutes."),
    _file("Car_insurance_policy.pdf", "Insurance", "2026-01-05T08:00",
          "Liberty Valley Auto Insurance. Policy number LV-7734-2210. Covered vehicle: 2014 Honda Civic. "
          "Roadside assistance: call 1-800-555-0144."),
    _email("101", "Maria Chen", "Welcome to Maple St!", "2026-08-14T18:20",
           "Hi Sam, welcome! The Wi-Fi network is Maple-204 and the password is sunflower-8817. "
           "The router is in the hallway closet. Let me know if anything is broken. Maria"),
    _email("102", "Prof. Nancy Lee", "CS589 HW3 posted", "2026-10-08T09:00",
           "Homework 3 (decision trees) is posted on the course site. It is due Wednesday, October 22 at 11:59 pm."),
    _email("103", "Prof. Nancy Lee", "CS589: HW3 deadline extended", "2026-10-17T15:40",
           "Because of the server outage, the HW3 deadline is extended to Friday, October 24 at 11:59 pm. "
           "Late days still apply after that."),
    _email("104", "SkyWay Airlines", "Your trip confirmation: Hartford to San Francisco", "2026-10-02T11:12",
           "Thanks for flying SkyWay. Confirmation code: K7QX2P. Flight SW 418 departs Hartford (BDL) on "
           "Friday, December 19 at 6:05 am and arrives in San Francisco (SFO) at 9:40 am. Seat 14C."),
    _email("105", "Bright Robotics Recruiting", "Your internship offer", "2026-10-10T13:00",
           "Congratulations! We're happy to offer you the Software Engineering Intern position. Your start date "
           "is Monday, June 1, 2027, at our Boston office. Please sign the offer by October 31."),
    _email("106", "Campus Rec Center", "Your membership is active", "2026-09-05T07:30",
           "Your gym membership is now active. Membership number: GM-55120. Show it at the front desk."),
    _email("107", "Du Bois Library", "Reminder: item due soon", "2026-10-15T08:00",
           "The book 'Pattern Recognition and Machine Learning' is due back on October 29, 2026. "
           "You can renew it online once."),
    _email("108", "Campus Rec Center", "Pool closed for maintenance", "2026-10-12T07:30",
           "The pool will be closed October 20-26 for maintenance. The gym stays open."),
    {"kind": "note", "ref": "note:1", "title": "bike lock code", "at": "2026-09-10T12:00", "version": "1",
     "text": "Note (to do): bike lock code is 4721"},
    {"kind": "note", "ref": "note:2", "title": "ask the professor about question 3", "at": "2026-10-16T14:00",
     "version": "1", "text": "Note (to do): ask the professor about question 3"},
    {"kind": "event", "ref": "event:1", "title": "Dentist: Amherst Dental", "at": "2026-10-30T15:15", "version": "1",
     "text": "Calendar event: Dentist: Amherst Dental. When: Thursday, October 30, 2026, 03:15 PM. Where: 12 Main St."},
    {"kind": "event", "ref": "event:2", "title": "CS589 lecture", "at": "2026-10-21T10:00", "version": "1",
     "text": "Calendar event: CS589 lecture. When: Tuesday, October 21, 2026, 10:00 AM. Where: Goessmann 20."},
]

# (question, source with the answer, words the answer must contain).
# Source None: nothing answers it, so Dock must say it couldn't find it.
QUESTIONS = [
    ("What's the Wi-Fi password the landlord sent me?", "email:101", ["sunflower-8817"]),
    ("How many late days do I get in CS589?", "file:/Users/sam/Documents/CS589/CS589_Syllabus_Fall2026.pdf", ["3"]),
    ("How many late days do I have in stat 310?", "file:/Users/sam/Documents/stat310/STAT310_syllabus.pdf", ["5"]),
    ("When is CS589 homework 3 due?", "email:103", ["24"]),
    ("What's my flight confirmation number?", "email:104", ["K7QX2P"]),
    ("What time does my flight to San Francisco leave?", "email:104", ["6:05"]),
    ("How much is my rent and when is it due?", "file:/Users/sam/Documents/Housing/Lease_Maple_St_204.pdf", ["950", "1"]),
    ("Where are the stat 310 office hours?", "file:/Users/sam/Documents/stat310/STAT310_syllabus.pdf", ["LGRT 1234"]),
    ("When's my dentist appointment?", "event:1", ["30"]),
    ("What's my bike lock code?", "note:1", ["4721"]),
    ("When does my internship start?", "email:105", ["June 1"]),
    ("What's my gym membership number?", "email:106", ["GM-55120"]),
    ("When is the CS589 midterm?", "file:/Users/sam/Documents/CS589/CS589_Syllabus_Fall2026.pdf", ["November 4"]),
    ("What are the quiet hours at my apartment?", "file:/Users/sam/Documents/Housing/Lease_Maple_St_204.pdf", ["10"]),
    ("When is my library book due?", "email:107", ["October 29"]),
    ("What's my car insurance policy number?", "file:/Users/sam/Documents/Insurance/Car_insurance_policy.pdf", ["LV-7734-2210"]),
    ("Can I turn in a CS305 essay late?", "file:/Users/sam/Documents/CS305/CS305_syllabus.docx", ["no"]),
    # Exact codes (keyword search) and loose wording (vector search).
    ("Which car is policy LV-7734-2210 for?", "file:/Users/sam/Documents/Insurance/Car_insurance_policy.pdf", ["Civic"]),
    ("What's the password for the internet at my place?", "email:101", ["sunflower-8817"]),
    ("By when do I have to sign the Bright Robotics offer?", "email:105", ["October 31"]),
    ("Is the pool open next week?", "email:108", ["closed"]),
    ("Who is my landlord?", "file:/Users/sam/Documents/Housing/Lease_Maple_St_204.pdf", ["Maria Chen"]),
    ("What's my passport number?", None, []),
    ("When is my CS320 final exam?", None, []),
    ("What did my mom say about Thanksgiving?", None, []),
]
