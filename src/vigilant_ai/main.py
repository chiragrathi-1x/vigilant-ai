import asyncio
import sys
import logging
from typing import Optional

import click

from src.vigilant_ai.database import init_db, SessionLocal
from src.vigilant_ai.models import Site
from src.vigilant_ai.engine import MonitoringEngine

# Configure logging to prevent information leakage and direct technical details to standard streams
logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


@click.group()
def cli():
    """Vigilant AI: Advanced Monitoring for Soft Failures.
    
    Identifies broken pages that return 200 OK using semantic drift 
    and statistical anomaly detection.
    """
    pass


@cli.command()
@click.option("--url", required=True, help="The URL to monitor.")
@click.option("--name", required=True, help="A friendly name for the site.")
@click.option("--interval", type=click.IntRange(min=1), default=60, help="Monitoring interval in seconds.")
@click.option(
    "--drift-threshold", 
    type=click.FloatRange(0.0, 1.0), 
    default=0.15, 
    help="Sensitivity for content drift (0.0 to 1.0)."
)
def add(url: str, name: str, interval: int, drift_threshold: float):
    """Add a new site to the monitoring engine."""
    init_db()
    
    if not (url.startswith("http://") or url.startswith("https://")):
        click.echo("Error: URL must start with 'http://' or 'https://'.", err=True)
        sys.exit(1)

    with SessionLocal() as db:
        try:
            new_site = Site(
                url=url,
                name=name,
                interval=interval,
                drift_threshold=drift_threshold,
                is_active=True
            )
            db.add(new_site)
            db.commit()
            click.echo(f"Successfully added {name} ({url}) to monitoring.")
        except Exception:
            db.rollback()
            logger.exception(f"Failed to add site: {name} ({url})")
            click.echo("Error: An internal error occurred while adding the site. Details logged.", err=True)
            sys.exit(1)


@cli.command()
def list_sites():
    """List all monitored sites and their current status."""
    init_db()
    with SessionLocal() as db:
        try:
            sites = db.query(Site).all()
            if not sites:
                click.echo("No sites are currently being monitored.")
                return

            click.echo(f"{'ID':<4} {'Name':<20} {'Interval':<10} {'Status':<10} {'URL'}")
            click.echo("-" * 70)
            for site in sites:
                status = "ACTIVE" if site.is_active else "INACTIVE"
                click.echo(f"{site.id:<4} {site.name[:20]:<20} {site.interval:<10} {status:<10} {site.url}")
        except Exception:
            logger.exception("Failed to list sites")
            click.echo("Error: Could not retrieve site list. Details logged.", err=True)


@cli.command()
@click.argument("site_id", type=int)
def remove(site_id: int):
    """Remove a site from monitoring by its ID."""
    init_db()
    with SessionLocal() as db:
        site = db.query(Site).filter(Site.id == site_id).first()
        if not site:
            click.echo(f"Site with ID {site_id} not found.", err=True)
            return

        try:
            db.delete(site)
            db.commit()
            click.echo(f"Removed site: {site.name}")
        except Exception:
            db.rollback()
            logger.exception(f"Failed to remove site ID: {site_id}")
            click.echo("Error: An internal error occurred while removing the site. Details logged.", err=True)


@cli.command()
@click.argument("site_id", type=int)
@click.option("--active/--inactive", default=True, help="Toggle monitoring status.")
def toggle(site_id: int, active: bool):
    """Pause or resume monitoring for a specific site."""
    init_db()
    with SessionLocal() as db:
        site = db.query(Site).filter(Site.id == site_id).first()
        if not site:
            click.echo(f"Site with ID {site_id} not found.", err=True)
            return

        try:
            site.is_active = active
            db.commit()
            status = "resumed" if active else "paused"
            click.echo(f"Monitoring {status} for {site.name}")
        except Exception:
            db.rollback()
            logger.exception(f"Failed to toggle site status for ID: {site_id}")
            click.echo("Error: An internal error occurred while updating status. Details logged.", err=True)


@cli.command()
@click.option("--concurrency", default=10, help="Maximum number of concurrent checks.")
def start(concurrency: int):
    """Start the monitoring daemon."""
    init_db()
    click.echo("Initializing Vigilant AI Engine...")
    engine = MonitoringEngine(concurrency=concurrency)
    
    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        click.echo("\nStopping Vigilant AI...")
    except Exception:
        logger.exception("Fatal engine error during runtime")
        click.echo("Error: A fatal engine error occurred. Check logs for details.", err=True)
        sys.exit(1)


@cli.command()
def stats():
    """Display high-level statistics of the monitoring performance."""
    init_db()
    from src.vigilant_ai.models import CheckResult
    from sqlalchemy import func
    
    with SessionLocal() as db:
        try:
            total_checks = db.query(CheckResult).count()
            soft_failures = db.query(CheckResult).filter(CheckResult.is_soft_failure == True).count()
            hard_failures = db.query(CheckResult).filter(CheckResult.status_code >= 400).count()
            
            click.echo("Vigilant AI Global Statistics")
            click.echo("============================")
            click.echo(f"Total Checks Performed: {total_checks}")
            click.echo(f"Soft Failures Detected: {soft_failures}")
            click.echo(f"Hard Failures (4xx/5xx): {hard_failures}")
            
            if total_checks > 0:
                avg_latency = db.query(func.avg(CheckResult.response_time_ms)).scalar()
                if avg_latency is not None:
                    click.echo(f"Average Latency:        {avg_latency:.2f}ms")
        except Exception:
            logger.exception("Failed to retrieve global statistics")
            click.echo("Error: Could not retrieve statistics. Details logged.", err=True)


if __name__ == "__main__":
    cli()
