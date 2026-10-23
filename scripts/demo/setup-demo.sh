#!/bin/bash
# Creates sample files for trying Dock: a project folder,
# some clutter in Documents and Downloads, and a Pages file with two versions.
#
#   scripts/demo/setup-demo.sh            # in your home folder
#   DEMO_HOME=/tmp/x scripts/demo/setup-demo.sh   # somewhere else (for a test)
#
# Existing files are never overwritten. Created files are listed in ~/.dock-demo-created
# for cleanup-demo.sh.
set -euo pipefail

HOME_DIR="${DEMO_HOME:-$HOME}"
DOCS="$HOME_DIR/Documents"
DOWNLOADS="$HOME_DIR/Downloads"
PROJECT="$DOCS/Project"
MANIFEST="$HOME_DIR/.dock-demo-created"
HERE="$(cd "$(dirname "$0")" && pwd)"
touch "$MANIFEST"

made() { echo "$1" >> "$MANIFEST"; echo "  + ${1#$HOME_DIR/}"; }

write() {  # write PATH  (text on stdin)
  local path="$1"
  if [ -e "$path" ]; then echo "  = ${path#$HOME_DIR/} (already there, skipped)"; cat >/dev/null; return; fi
  folder "$(dirname "$path")"
  cat > "$path"
  made "$path"
}

# PDF or Word file from text (cupsfilter / textutil).
pdf() {  # pdf PATH  (text on stdin)
  local path="$1" tmp; tmp="$(mktemp).txt"; cat > "$tmp"
  if [ -e "$path" ]; then echo "  = ${path#$HOME_DIR/} (skipped)"; rm "$tmp"; return; fi
  folder "$(dirname "$path")"
  cupsfilter "$tmp" > "$path" 2>/dev/null; rm "$tmp"; made "$path"
}
docx() {
  local path="$1" tmp; tmp="$(mktemp).txt"; cat > "$tmp"
  if [ -e "$path" ]; then echo "  = ${path#$HOME_DIR/} (skipped)"; rm "$tmp"; return; fi
  folder "$(dirname "$path")"
  textutil -convert docx "$tmp" -output "$path"; rm "$tmp"; made "$path"
}
folder() { [ -d "$1" ] || { mkdir -p "$1"; made "$1"; }; }

echo "Project folder:"
folder "$PROJECT"
folder "$PROJECT/Photos"
write "$PROJECT/Photos/PUT YOUR PHOTOS HERE.txt" <<'TXT'
Put 3 or 4 photos you took yourself here (recycling bins, a hallway, a mailroom: anything
that fits the proposal). Then drag them into Project Proposal.pages.
TXT
write "$PROJECT/Research Notes.txt" <<'TXT'
Research notes: community recycling program

- Most mixed bins end up contaminated when signs are unclear; clear labels and photos on the bins help.
- Single-stream (one bin for all recyclables) is easier for people, but sorting costs more later.
- Pilot idea: 3 locations for 6 weeks, weigh the bins every Friday.
- Ask facilities for last year's waste numbers.
TXT
cat <<'CSV' | write "$PROJECT/Budget.csv"
Item,Quantity,Unit cost,Total
Labelled recycling bins,12,45,540
Printed signs,30,3,90
Weekly pickup (6 weeks),6,40,240
Volunteer t-shirts,15,8,120
Total,,,990
CSV
docx "$PROJECT/Meeting Notes - Oct 14.docx" <<'TXT'
Meeting notes, October 14

- Agreed on 3 pilot locations: the main lobby, the cafeteria, the second-floor printer room.
- Need photos of the current bins for the proposal.
- Proposal due Thursday 11:59 PM, as one PDF.
TXT

echo "Everyday clutter in Documents (so finding things by hand looks real):"
docx "$DOCS/Templates/Cover Letter Template.docx" <<<"Dear [Name], ..."
docx "$DOCS/Templates/Weekly Report Template.docx" <<<"Weekly report: what I did, what's next, blockers."
pdf "$DOCS/Receipts/Receipt - Office Supplies.pdf" <<<"Receipt: notebooks x3, pens x10. Total \$18.40"
pdf "$DOCS/Receipts/Receipt - Train Ticket.pdf" <<<"Train ticket, Oct 3. Total \$12.75"
write "$DOCS/Archive 2025/Old Ideas.txt" <<<"Ideas from last year: a book swap shelf, a bike repair day, a plant swap."
docx "$DOCS/Archive 2025/Proposal Draft (old).docx" <<<"An old draft about a book swap shelf. Not the current project."
write "$DOCS/Meeting Notes/Sep 30.txt" <<<"Kickoff: pick one project for the term."
write "$DOCS/Meeting Notes/Oct 7.txt" <<<"Chose the recycling program. Everyone takes photos of bins near them."

echo "Downloads clutter:"
pdf "$DOWNLOADS/syllabus_fall.pdf" <<<"Course schedule and policies."
pdf "$DOWNLOADS/invoice_10422.pdf" <<<"Invoice 10422. Amount due \$45.00"
pdf "$DOWNLOADS/event-flyer.pdf" <<<"Volunteer fair, Friday at noon."
docx "$DOWNLOADS/notes (1).docx" <<<"Random notes."
docx "$DOWNLOADS/notes (2).docx" <<<"More random notes."

echo "The proposal (Pages), saved twice so File > Revert To > Browse All Versions has an older version:"
osascript "$HERE/make-proposal.applescript" "$PROJECT/Project Proposal.pages" && made "$PROJECT/Project Proposal.pages" || true

echo
echo "Done."
