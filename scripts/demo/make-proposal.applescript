-- Creates "Project Proposal.pages" with two saved versions (with and without the
-- Budget section), for testing version recovery. Skips an existing file.
on run argv
	set thePath to item 1 of argv
	tell application "System Events" to set already to exists disk item thePath
	if already then
		log "  = Project Proposal.pages already exists (skipped)"
		error number -128
	end if

	set intro to "Project Proposal: Community Recycling Program" & return & return & ¬
		"Goal" & return & "Cut the waste we send to landfill by making recycling easy: clear bins, clear signs, and a short pilot to measure what works." & return & return & ¬
		"The problem" & return & "Our current bins are unlabelled and often mixed, so most of what goes in them can't be recycled. People want to recycle, but they don't know which bin to use." & return & return & ¬
		"The plan" & return & "A six-week pilot in three places: the main lobby, the cafeteria and the second-floor printer room. Each gets labelled bins with photos of what goes in them. Volunteers weigh the bins every Friday." & return & return
	set budget to "Budget" & return & "About $990 in total: twelve labelled bins ($540), printed signs ($90), weekly pickup for six weeks ($240) and volunteer t-shirts ($120). Facilities has offered to cover the pickup." & return & return
	set closing to "How we'll measure it" & return & "We'll compare the weight of recycling and trash each week with last year's numbers, and survey people at the end of the pilot." & return & return & ¬
		"Next steps" & return & "Approve the pilot, order the bins, and start the first week on November 3."

	tell application "Pages"
		set doc to make new document with properties {document template:template "Blank"}
		set body text of doc to intro & budget & closing
		save doc in POSIX file thePath
		delay 2
		set body text of doc to intro & closing
		save doc
		close doc saving yes
	end tell
end run
