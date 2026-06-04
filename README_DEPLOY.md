# Swing Trader Cloud Deployment

This folder is a separate cloud version of the local app. It does not modify or depend on the localhost `app/` folder.

## What This Version Uses

- Streamlit Community Cloud for the website.
- Neon or Supabase Postgres for the persistent database.
- GitHub Actions for the daily scheduled scan.
- Yahoo Finance daily candles for NSE symbols.

## Files To Deploy

Use this whole `streamlit_cloud` folder as the root of the GitHub repository you deploy.

Main app file:

```text
streamlit_app.py
```

Daily automation file:

```text
.github/workflows/daily-cloud.yml
```

## Step 1: Create A Postgres Database

Choose one:

- Neon Postgres
- Supabase Postgres

Create a project and copy the pooled Postgres connection string. It will look roughly like:

```text
postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require
```

Keep it private. It is a password.

## Step 2: Put This Folder On GitHub

Create a new GitHub repository, then upload/push the contents of this `streamlit_cloud` folder.

The repository root should contain:

```text
streamlit_app.py
requirements.txt
cloud_app/
scripts/
.github/
.streamlit/
```

## Step 3: Add GitHub Actions Secret

In the GitHub repo:

1. Open **Settings**.
2. Open **Secrets and variables**.
3. Open **Actions**.
4. Add a new repository secret:

```text
DATABASE_URL
```

Paste the Postgres connection string as the value.

## Step 4: Deploy On Streamlit

In Streamlit Community Cloud:

1. Sign in with GitHub.
2. Choose the GitHub repository.
3. Set the main file path to:

```text
streamlit_app.py
```

4. Open app secrets.
5. Add:

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require"
```

6. Deploy.

## Step 5: Run First Scan

After the app opens:

1. Click **Run Daily Workflow** inside the Streamlit app.
2. Wait for it to fetch data, backtest, and scan.
3. Check **Today's Setups**.

## Step 6: Enable Daily Automation

The GitHub Action is already included:

```text
.github/workflows/daily-cloud.yml
```

It runs at 18:45 UTC, which is 00:15 IST, Monday-Friday. You can also run it manually from the GitHub **Actions** tab.

## Important Limits

- This is research only, not financial advice.
- It does not place broker orders.
- GitHub scheduled workflows can be delayed sometimes.
- Streamlit Community Cloud can sleep when unused; GitHub Actions is what refreshes the database while your laptop is off.
- If your database provider pauses or rotates credentials, update `DATABASE_URL` in both GitHub and Streamlit.

