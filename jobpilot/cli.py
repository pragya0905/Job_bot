import argparse
import asyncio
import sys

from sqlmodel import select

from jobpilot.db import get_session, init_db
from jobpilot.models import Job, JobScore, ScanRun, User
from jobpilot.pipeline.runner import run_scan


def _resolve_user(session, email: str) -> User:
    user = session.exec(select(User).where(User.email == email.strip().lower())).first()
    if user is None:
        print(f"No account found for '{email}'. Sign up first at /signup, or check the email.")
        sys.exit(1)
    return user


def cmd_run_scan(args: argparse.Namespace) -> None:
    init_db()
    with get_session() as session:
        user = _resolve_user(session, args.email)
        scan_run = ScanRun(user_id=user.id, status="running", stage="collecting")
        session.add(scan_run)
        session.commit()
        session.refresh(scan_run)
        run_id = scan_run.id

    print(f"Starting scan run #{run_id} for {args.email}...")
    asyncio.run(run_scan(run_id))

    with get_session() as session:
        scan_run = session.get(ScanRun, run_id)
        print(
            f"Scan #{run_id} {scan_run.status}: "
            f"collected={scan_run.jobs_collected} filtered={scan_run.jobs_filtered} "
            f"scored={scan_run.jobs_scored} tailored={scan_run.jobs_tailored}"
        )
        if scan_run.error_log:
            print("Warnings/errors:\n" + scan_run.error_log)


def cmd_list_jobs(args: argparse.Namespace) -> None:
    init_db()
    with get_session() as session:
        user = _resolve_user(session, args.email)
        rows = session.exec(
            select(Job, JobScore)
            .where(Job.user_id == user.id)
            .join(JobScore, JobScore.job_id == Job.id, isouter=True)
        ).all()

    rows = [r for r in rows if (r[1].score if r[1] else 0) >= args.min_score]
    rows.sort(key=lambda r: (r[1].score if r[1] else -1), reverse=True)

    for job, score in rows:
        score_label = score.score if score else "—"
        print(f"[{score_label!s:>3}] {job.title} @ {job.company_name} ({job.location_raw}) - {job.url}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="jobpilot")
    sub = parser.add_subparsers(dest="command", required=True)

    run_scan_parser = sub.add_parser("run-scan", help="Collect, score, and tailor drafts in one manually-triggered run")
    run_scan_parser.add_argument("--email", required=True, help="Account email to run the scan for")
    run_scan_parser.set_defaults(func=cmd_run_scan)

    list_parser = sub.add_parser("list-jobs", help="List collected jobs sorted by fit score")
    list_parser.add_argument("--email", required=True, help="Account email to list jobs for")
    list_parser.add_argument("--min-score", type=int, default=0, dest="min_score")
    list_parser.set_defaults(func=cmd_list_jobs)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
