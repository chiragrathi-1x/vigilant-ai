import abc
import json
import logging
from typing import Any, Dict, List, Optional, Type

import httpx

logger = logging.getLogger("vigilant_ai.notifiers")


class NotificationError(Exception):
    """Raised when a notification fails to send."""
    pass


class BaseNotifier(abc.ABC):
    """
    Abstract base class for all notification providers.
    Implementing classes should handle the specifics of formatting and delivery.
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config

    @abc.abstractmethod
    async def send(self, site_name: str, status_message: str, details: Dict[str, Any]) -> bool:
        """
        Sends a notification.
        
        :param site_name: Name of the monitored site.
        :param status_message: A summary of the failure or recovery.
        :param details: Dictionary containing metadata (latency, drift score, error keys).
        :return: True if successful, False otherwise.
        """
        pass


class ConsoleNotifier(BaseNotifier):
    """Simple notifier that outputs alerts to the local log/console."""

    async def send(self, site_name: str, status_message: str, details: Dict[str, Any]) -> bool:
        log_msg = f"ALERT [{site_name}]: {status_message} | Details: {json.dumps(details)}"
        logger.info(log_msg)
        return True


class SlackNotifier(BaseNotifier):
    """Sends notifications to Slack via Webhooks."""

    async def send(self, site_name: str, status_message: str, details: Dict[str, Any]) -> bool:
        webhook_url = self.config.get("webhook_url")
        if not webhook_url:
            raise NotificationError("Slack webhook_url is missing in configuration.")

        # Constructing Slack Block Kit message for a production-grade look
        payload = {
            "text": f"Vigilant AI Alert: {site_name}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "🚨 Vigilant AI Monitoring Alert"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Site:*\n{site_name}"},
                        {"type": "mrkdwn", "text": f"*Status:*\n{status_message}"}
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Analysis Details:*\n```\n{json.dumps(details, indent=2)}\n```"
                    }
                }
            ]
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
                return True
        except httpx.HTTPError as e:
            logger.error(f"Failed to send Slack notification for {site_name}: {e}")
            return False


class DiscordNotifier(BaseNotifier):
    """Sends notifications to Discord via Webhooks."""

    async def send(self, site_name: str, status_message: str, details: Dict[str, Any]) -> bool:
        webhook_url = self.config.get("webhook_url")
        if not webhook_url:
            raise NotificationError("Discord webhook_url is missing in configuration.")

        color = 15158332  # Red for alerts
        if "recovered" in status_message.lower() or "ok" in status_message.lower():
            color = 3066993  # Green for recoveries

        payload = {
            "username": "Vigilant AI",
            "embeds": [{
                "title": f"Monitoring Alert: {site_name}",
                "description": status_message,
                "color": color,
                "fields": [
                    {"name": k, "value": str(v), "inline": True} 
                    for k, v in details.items() if k != "content"
                ],
                "footer": {"text": "Vigilant AI - Heuristic Monitoring Engine"}
            }]
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
                return True
        except httpx.HTTPError as e:
            logger.error(f"Failed to send Discord notification for {site_name}: {e}")
            return False


class WebhookNotifier(BaseNotifier):
    """Generic Webhook notifier for custom integrations (e.g., PagerDuty, Zapier)."""

    async def send(self, site_name: str, status_message: str, details: Dict[str, Any]) -> bool:
        webhook_url = self.config.get("url")
        headers = self.config.get("headers", {})
        
        if not webhook_url:
            raise NotificationError("Generic Webhook URL is missing.")

        payload = {
            "event": "vigilant_ai_alert",
            "site": site_name,
            "message": status_message,
            "data": details
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(webhook_url, json=payload, headers=headers)
                response.raise_for_status()
                return True
        except httpx.HTTPError as e:
            logger.error(f"Failed to send generic Webhook for {site_name}: {e}")
            return False


class NotifierRegistry:
    """Registry to manage and instantiate notification providers."""

    _providers: Dict[str, Type[BaseNotifier]] = {
        "slack": SlackNotifier,
        "discord": DiscordNotifier,
        "webhook": WebhookNotifier,
        "console": ConsoleNotifier
    }

    def __init__(self):
        self.enabled_notifiers: List[BaseNotifier] = []

    def configure_from_settings(self, settings: List[Dict[str, Any]]):
        """
        Initializes notifiers based on a list of configurations.
        Example settings: 
        [
            {"type": "slack", "name": "prod-alerts", "webhook_url": "https://..."},
            {"type": "console", "name": "local-logs"}
        ]
        """
        for config in settings:
            n_type = config.get("type")
            n_name = config.get("name", n_type)
            
            provider_cls = self._providers.get(n_type)
            if provider_cls:
                notifier_instance = provider_cls(n_name, config)
                self.enabled_notifiers.append(notifier_instance)
                logger.debug(f"Initialized notifier: {n_name} ({n_type})")
            else:
                logger.warning(f"Unknown notifier type: {n_type}")

    async def notify_all(self, site_name: str, status_message: str, details: Dict[str, Any]):
        """Dispatches an alert to all configured notifiers."""
        if not self.enabled_notifiers:
            logger.warning("No notifiers configured. Alert dropped.")
            return

        for notifier in self.enabled_notifiers:
            try:
                success = await notifier.send(site_name, status_message, details)
                if success:
                    logger.info(f"Notification sent successfully via {notifier.name}")
            except Exception as e:
                logger.error(f"Error dispatching notification via {notifier.name}: {str(e)}")


# Singleton instance for the service
notifier_registry = NotifierRegistry()

async def dispatch_alert(site_name: str, message: str, metadata: Optional[Dict[str, Any]] = None):
    """Utility function to be called from the engine/analyzer logic."""
    details = metadata or {}
    await notifier_registry.notify_all(site_name, message, details)
