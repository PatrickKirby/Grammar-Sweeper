# Security Policy

## Supported versions

Only the latest commit on the default branch is supported. There are no maintained older versions.

## Reporting a vulnerability

Do not open a public issue for a security problem.

Report privately through GitHub's [Security Advisories](../../security/advisories/new) for this repository, or contact
the maintainer through [theapertura.substack.com](https://theapertura.substack.com). Include a description, the steps
that trigger it, and the impact you would expect. Do not post the details in a public comment.

Expect an initial response within 7 days. This is a solo-maintained utility, not a funded project. Fixes ship as time
allows, not on an SLA.

## Scope

The program runs entirely on your machine. It makes no network calls and sends no telemetry. The only links it opens are
the footer links and the optional coffee button, which open a web page in your browser. It automates the Grammarly panel
inside Microsoft Word through Windows UI Automation, so it reads window contents and sends clicks to windows on your
desktop.

The installer is the one part that uses the network. During setup it downloads three files from PyPI
(`files.pythonhosted.org`): `PySide6_Essentials`, `shiboken6` and `Pillow`. It contacts nothing else. Each download is checked
against a SHA-256 hash pinned in the installer, and a file that does not match is never unpacked.

The realistic risk surface is:

- Files written to `%APPDATA%\Grammar Sweeper`: settings, logs, screenshots of the Grammarly panel, and diagnostic
  bundles. Screenshots and the report can contain text from your document. Treat a diagnostic bundle as sensitive
  before you share it, and delete old files from the Advanced tab with Delete selected.
- The installer's download and unpack of the Qt and Pillow runtime: the pinned URLs and hashes in `installer/runtime.inc`, or
  anything that lets a file other than the pinned one be unpacked or written outside the install folder.
- Path handling that could read or write outside the settings folder or the folder of the document being swept.
- Any behaviour that applies a change to a document other than the one you picked, or acts while a different window is
  in front.

The tool is unofficial and unaffiliated with Grammarly. Whether automating Grammarly's interface is allowed by their
terms is for you to check. That is a policy question, not a vulnerability, so please do not report it here.

Report anything in the shape above even if you are unsure it is exploitable.
