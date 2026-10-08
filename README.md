# Instagram Likes Batch Unliker

A Windows Python/Selenium tool for removing liked Instagram media in
small, verified batches.

The portable runner uses a local Firefox profile for each user. It does not
contain or distribute an Instagram login session. Each user signs in manually
the first time.

## Important safety information

This tool performs destructive actions: it removes items from the Instagram
account that is currently signed in. Start with one small batch and inspect
the result before running more batches.

- Use only with an account you own or are authorized to manage.
- Review the selected count before confirming an Unlike operation.
- Do not share your Firefox profile, cookies, passwords, or access tokens.
- Do not commit `ig_selenium_profile` or runtime logs to GitHub.
- Instagram may change its interface at any time. Stop if the page does not
  behave as expected.

## Requirements

Each computer running the tool needs:

1. Windows 10 or newer.
2. Python 3.11 or newer.
3. Mozilla Firefox.
4. Internet access.

Selenium is installed from `requirements.txt`; it does not need to be
installed globally.

## Installation from GitHub

Open PowerShell and run:

```powershell
git clone https://github.com/YOUR_USERNAME/ig_dislike.git
cd ig_dislike
```

Create a project-specific virtual environment:

```powershell
python -m venv .venv
```

Allow activation scripts for the current PowerShell window and activate the
environment:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

Install the project dependency:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell activation is unavailable, use the virtual-environment Python
directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## First run

Run one small controlled batch:

```powershell
.\.venv\Scripts\python.exe -m src.main unlike-portable --batch-size 10 --max-batches 1
```

The runner will:

1. Find Firefox automatically.
2. Create `ig_selenium_profile` inside the project directory.
3. Open Instagram's Likes page.
4. Wait for the user to log in manually if needed.
5. Select only the configured target media.
6. Verify Instagram's selected count before Unlike.
7. Confirm the Unlike operation through the Instagram dialog.
8. Reload and verify that normal mode is restored before another batch.

Do not close Firefox while a batch is being verified or recovered.

## Running more batches

The default portable command runs one batch of up to 80 items:

```powershell
.\.venv\Scripts\python.exe -m src.main unlike-portable
```

Specify the batch size and maximum number of batches explicitly:

```powershell
.\.venv\Scripts\python.exe -m src.main unlike-portable --batch-size 50 --max-batches 3
```

Use small values while testing. `--batch-size` is a maximum; Instagram may
render fewer eligible cards than requested.

## Logs

Runtime logs are written to:

```text
logs\batch_unliker_YYYYMMDD_HHMMSS.log
```

If a run stops or reports an error, save the relevant log when asking for
help. Do not include browser profiles, cookies, passwords, or other private
account data.

## Local files created at runtime

These files and folders are machine-specific and should remain local:

```text
.venv\
ig_selenium_profile\
logs\
__pycache__\
```

The repository `.gitignore` excludes them. Never copy an authenticated
`ig_selenium_profile` to another person or commit it to GitHub.

## Available commands

Portable runner recommended for other computers:

```powershell
python -m src.main unlike-portable --batch-size 10 --max-batches 1
```

The repository also contains experimental runners:

```powershell
python -m src.main unlike-v2
python -m src.main unlike-v3
python -m src.main unlike-v4
```

Use `unlike-portable` on another computer because it discovers Firefox and
uses a local per-user profile. The other runners may depend on local
configuration and are not the recommended sharing interface.

## Development checks

Before submitting changes:

```powershell
.\.venv\Scripts\python.exe -m py_compile src\batch_unliker_portable.py src\batch_unliker_v4.py
git diff --check
```
