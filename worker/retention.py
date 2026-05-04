import logging
import time
from datetime import timedelta

from sqlmodel import Session, select, func, delete

from app.core.config import configure_logging, settings
from app.core.db import engine
from app.core.time import utc_now_naive
from app.models.greenhouse import Greenhouse
from app.models.telemetry import Telemetry
from app.models.tenant import Subscription, Plan, SubscriptionStatus

logger = logging.getLogger(__name__)

def purge_old_telemetry():
    """Purge telemetry data based on tenant retention plans."""
    with Session(engine) as session:
        # 1. Get all billable/trial subscriptions and their plans
        statement = (
            select(Subscription, Plan)
            .join(Plan)
            .where(
                Subscription.status.in_(
                    [SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING]
                )
            )
        )
        results = session.exec(statement).all()
        
        total_purged = 0
        now = utc_now_naive()

        for subscription, plan in results:
            retention_days = plan.telemetry_retention_days
            if not retention_days:
                continue # No retention policy for this plan (infinite?)
            
            # Find all greenhouses belonging to this tenant
            greenhouse_statement = select(Greenhouse.id).where(Greenhouse.tenant_id == subscription.tenant_id)
            greenhouse_ids = session.exec(greenhouse_statement).all()
            
            if not greenhouse_ids:
                continue
                
            cutoff_date = now - timedelta(days=retention_days)
            
            # Delete telemetry for these greenhouses older than cutoff_date
            delete_statement = (
                delete(Telemetry)
                .where(Telemetry.greenhouse_id.in_(greenhouse_ids))
                .where(Telemetry.time < cutoff_date)
            )
            
            result = session.exec(delete_statement)
            purged_count = result.rowcount
            total_purged += purged_count
            
            if purged_count > 0:
                logger.info(
                    "Purged %d telemetry records for tenant=%s (retention=%d days)",
                    purged_count, subscription.tenant_id, retention_days
                )
        
        if total_purged > 0:
            session.commit()
            logger.info("Successfully purged total of %d records", total_purged)

def main():
    configure_logging()
    logger.info("Starting Telemetry Retention Worker")
    
    interval = settings.RETENTION_CHECK_INTERVAL_SECONDS if hasattr(settings, "RETENTION_CHECK_INTERVAL_SECONDS") else 3600
    
    while True:
        try:
            logger.info("Running retention purge...")
            purge_old_telemetry()
        except Exception as e:
            logger.exception("Error during retention purge: %s", e)
        
        logger.info("Waiting %d seconds for next run...", interval)
        time.sleep(interval)

if __name__ == "__main__":
    main()
