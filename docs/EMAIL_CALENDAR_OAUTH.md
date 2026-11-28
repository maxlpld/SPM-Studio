# E-mail and calendar accounts — step by step

Agent Hub connects to your mailbox and calendars **from your own computer**. Nothing goes through a server of
ours, and no OAuth client id or secret ships with Agent Hub: when you want "Sign in with Google / Microsoft", you
create your own (free) client id once. Passwords, app passwords, refresh tokens and an optional client secret are
stored only in the **system keyring** (GNOME Keyring / KWallet, macOS Keychain, Windows Credential Manager). Without
a keyring they are kept in memory for the session only — never in a file.

**Sending rule.** The assistant can read, search, summarise and draft. Sending, replying, forwarding and moving
e-mail always show the full message (recipients, subject, text, attachments) with **Edit / Send / Discard**; it
leaves only when you press Send. Full access does not change this.

## 1. The simplest way: an app password (IMAP / SMTP)

Works with Gmail, Outlook.com, iCloud, Yahoo, GMX, Fastmail and almost every university or company server.

1. Agent Hub › Settings › **E-mail accounts** › *Add account…*
2. Choose your provider (the servers are filled in) or *Other* and type the IMAP / SMTP servers your IT service
   gives you (usually IMAP port 993 SSL, SMTP port 587 STARTTLS or 465 SSL).
3. Type your address and an **app password**:
   * Gmail: turn on 2-step verification, then create an app password at <https://myaccount.google.com/apppasswords>.
   * iCloud: <https://appleid.apple.com> › Sign-In and Security › App-Specific Passwords.
   * Yahoo: Account Security › Generate app password. Outlook.com: Security › Advanced security options.
4. *Test connection*, then *Save*.

## 2. Sign in with Google (Gmail and Google Calendar)

1. Open <https://console.cloud.google.com/>, create a project (any name).
2. *APIs & Services › Library*: enable **Gmail API** (for e-mail) and/or **Google Calendar API**.
3. *APIs & Services › OAuth consent screen*: user type *External*, fill in the app name and your e-mail, add
   yourself under *Test users*. (While the app is in "testing", only test users can sign in — that is you.)
   Scopes: `https://mail.google.com/` (e-mail) and `https://www.googleapis.com/auth/calendar` (calendar).
4. *APIs & Services › Credentials › Create credentials › OAuth client ID* › application type **Desktop app**.
5. Copy the **Client ID** into Agent Hub (E-mail account › *Sign in with Google*, or Calendar › Two-way sync ›
   Google Calendar). Google also shows a "client secret" for desktop clients; Google documents that it is not
   confidential for installed apps, but Agent Hub still keeps it only in the keyring. Never commit it anywhere.
6. Your browser opens; sign in and allow access. Agent Hub receives the code on `http://127.0.0.1:<port>` (PKCE,
   no server involved) and keeps the refresh token in the keyring.

## 3. Sign in with Microsoft (Microsoft 365 / Outlook, through Microsoft Graph)

1. Open <https://entra.microsoft.com/> › *Applications › App registrations › New registration*.
2. Name: anything. Supported account types: *Accounts in any organizational directory and personal Microsoft
   accounts* (or only your organisation).
3. Redirect URI: platform **Mobile and desktop applications**, URI `http://localhost`.
4. *Authentication*: enable **Allow public client flows**.
5. *API permissions › Microsoft Graph › Delegated*: `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`,
   `User.Read`, `offline_access`.
6. Copy the **Application (client) ID** into Agent Hub. For a work or school account restricted to your
   organisation, also type the **Directory (tenant) ID** (otherwise `common`). No client secret is needed.
7. Sign in in the browser; the refresh token goes to the keyring.

Your organisation may require an administrator to approve the app; ask your IT service if sign-in is refused.

## 4. iCloud and other CalDAV calendars

Calendar › Two-way sync › *iCloud (CalDAV)* (server `https://caldav.icloud.com/`) or *Other CalDAV server*
(Nextcloud: `https://<server>/remote.php/dav/`, Fastmail: `https://caldav.fastmail.com/`). Type your Apple ID /
user name and an **app-specific password**, press *Connect*, choose the calendar.

## 5. Read-only subscriptions

Calendar › *Subscribe to a URL*: any `https://` or `webcal://` iCal address (public holidays, a seminar series,
a shared calendar). It is refreshed at the interval you choose and stays read-only.

## What runs in the background

Only when an account is connected: e-mail is checked every few minutes (or at once with IMAP IDLE when the server
supports it), subscriptions and synced calendars at their intervals, reminders every 30 seconds. With no account
connected, nothing is checked.

## Removing an account

Settings › E-mail accounts › *Remove* deletes the account and its password / token from the keyring. To revoke
the OAuth grant too: Google <https://myaccount.google.com/permissions>, Microsoft
<https://myaccount.microsoft.com/> › Apps.
