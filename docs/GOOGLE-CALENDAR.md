# Sign in with Google (Calendar and Gmail): one-time setup for the developer

Users connect their Google Calendar and Gmail with one button ("Sign in with Google" in Dock's welcome window): Google's sign-in page opens, they pick their account and click **Allow**. There are no links or app passwords to paste. For that button to work, Dock has to be registered with Google **once**. This takes about 5 minutes and is free.

## Steps (Google Cloud Console)
1. Go to <https://console.cloud.google.com/> and sign in with your Google account. At the top, **Select a project › New project**, name it **Dock**, and create it.
2. **APIs & Services › Library**: search **Google Calendar API** and click **Enable**.
3. **Google Auth Platform › Branding** (the "OAuth consent screen"): app name **Dock**, your email as the support and developer contact. Save.
4. **Audience**: choose **External**, and stay in **Testing** (don't publish). Under **Test users**, click **Add users** and add the Gmail address(es) you'll connect.
   - Testing needs no app domain, homepage or privacy policy: leave those Branding fields empty. Publishing (and Google's review) asks for them, and the Gmail permission also needs a paid security review, so it isn't worth it for the hackathon.
   - In Testing, Google ends each sign-in after 7 days: click **Connect** again in Dock's window when that happens. Only the test users you added can sign in (up to 100).
5. **Data access › Add or remove scopes**: add `.../auth/calendar.readonly` (read your calendars), `.../auth/calendar.events` (add your reminders and deadlines to the calendar) and `https://mail.google.com/` (Gmail through IMAP, which Dock uses to read and, only after the user says yes, file or trash email). Also enable the **Gmail API** in the Library (Dock uses it once, to learn the address). Save.
   - `https://mail.google.com/` is a *restricted* scope: until Google reviews Dock, users see "Google hasn't verified this app" and click **Advanced › Go to Dock** once, and at most 100 people can use it. Fine for the hackathon.
6. **Clients › Create client**: application type **Desktop app**, name **Dock**, **Create**, then **Download JSON**.
7. Save the downloaded file as **`server/google_oauth_client.json`** in the Dock folder.

Restart Dock. The welcome window now shows **Sign in with Google**.

## Notes
- **One sign-in for both:** the sign-in is kept in `server/.data/google_token.json` (and which permissions were given, with the address, in `google_account.json`), only on that computer. **Sign out** removes it. If the user unticks Calendar or Gmail on Google's page, Dock connects the other and says which one is missing.
- **What Dock can see:** the calendars the user has ticked in Google Calendar; it only adds events (reminders and deadlines the user asked for) and never changes or deletes existing ones. Gmail: Dock only reads, and files or trashes email only after the user says yes to a clean-up.
- **The client file:** for a desktop app, Google treats this file as not secret, since every copy of an installed app contains it. Committing it lets anyone who clones the repo use the button. The trade-off is that others could reuse your Google project's (free) quota. To avoid that, leave it out of git and each developer makes their own.
- **No button?** Without the file, the welcome window says Google sign-in isn't set up yet: add the file and restart Dock.
- **Windows:** the same button and code work on Windows. Nothing here is Mac-specific.
