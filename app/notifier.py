"""Event notification system for n8n webhook integration."""
import logging
import json
from typing import Any, Dict
from datetime import datetime
import requests
from config import Config

logger = logging.getLogger(__name__)


class Notifier:
    """Send events to n8n webhook. Never raises exceptions to protect the bot."""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url
        self.session = requests.Session()
        self.session.timeout = 5  # 5 second timeout

    def send_event(self, event_type: str, data: Dict[str, Any]) -> bool:
        """
        Send event to n8n webhook.
        
        Args:
            event_type: Type of event (e.g., 'started', 'stopped', 'heartbeat')
            data: Event payload
            
        Returns:
            True if sent successfully, False otherwise
        """
        try:
            payload = {
                "timestamp": datetime.utcnow().isoformat(),
                "event_type": event_type,
                "bot_name": Config.BOT_NAME,
                "data": data,
            }
            
            response = self.session.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=5
            )
            
            if response.status_code >= 400:
                logger.warning(
                    f"Webhook returned {response.status_code}: {response.text[:200]}"
                )
                return False
                
            logger.debug(f"Event sent: {event_type}")
            return True
            
        except requests.exceptions.Timeout:
            logger.warning(f"Webhook timeout sending {event_type}")
            return False
        except requests.exceptions.ConnectionError:
            logger.warning(f"Webhook connection error sending {event_type}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending webhook event: {e}", exc_info=True)
            return False

    def send_heartbeat(self, metrics: Dict[str, Any]) -> bool:
        """Send heartbeat with bot metrics."""
        return self.send_event("heartbeat", metrics)

    def send_started(self) -> bool:
        """Send bot started event."""
        return self.send_event("started", {"message": "Trading bot started"})

    def send_stopped(self) -> bool:
        """Send bot stopped event."""
        return self.send_event("stopped", {"message": "Trading bot stopped"})
