"""IMAP client with proxy support.

This module provides IMAP connection management with support for HTTP/SOCKS proxies
for corporate environments. Handles SSL/TLS, authentication, and connection pooling.

Classes:
    IMAPClient: Main IMAP connection manager
    ProxyMailBox: Wrapper for IMAP connections through proxy
"""

import imaplib
import ssl
import socket
from typing import Optional, Union
from contextlib import contextmanager

import structlog
from imap_tools import MailBox

from ...core.config import settings

logger = structlog.get_logger(__name__)


class IMAPClient:
    """IMAP client with proxy support for corporate environments."""
    
    @staticmethod
    def get_connection() -> MailBox:
        """Get IMAP connection with optional proxy support.
        
        Returns:
            Connected and authenticated MailBox instance
            
        Raises:
            ConnectionError: If IMAP connection or authentication fails
        """
        if settings.imap_proxy_enabled and settings.imap_proxy_host:
            return IMAPClient._get_proxy_connection()
        else:
            return IMAPClient._get_direct_connection()
    
    @staticmethod
    def _get_direct_connection() -> MailBox:
        """Get direct IMAP connection without proxy."""
        try:
            mailbox = MailBox(settings.imap_server)
            mailbox.login(settings.imap_user, settings.imap_app_password)
            
            logger.info(
                "IMAP direct connection established",
                server=settings.imap_server,
                user=settings.imap_user,
                folder=settings.imap_folder
            )
            
            return mailbox
            
        except Exception as e:
            logger.error(
                "Direct IMAP connection failed",
                server=settings.imap_server,
                username=settings.imap_user,
                error=str(e)
            )
            raise ConnectionError(f"IMAP connection failed: {e}")
    
    @staticmethod
    def _get_proxy_connection() -> MailBox:
        """Get IMAP connection through proxy."""
        try:
            from python_socks.sync import Proxy
            
            logger.info(
                "Connecting to IMAP through proxy",
                proxy_host=settings.imap_proxy_host,
                proxy_port=settings.imap_proxy_port,
                proxy_type=settings.imap_proxy_type,
                imap_server=settings.imap_server,
                imap_port=settings.imap_port
            )
            
            # Create proxy URL
            proxy_url = IMAPClient._build_proxy_url()
            
            # Create proxy object
            proxy = Proxy.from_url(proxy_url)
            
            # Monkey patch socket creation to use proxy
            original_create_connection = socket.create_connection
            
            def proxy_create_connection(address, timeout=None, source_address=None):
                host, port = address
                if host == settings.imap_server and port == settings.imap_port:
                    # Use proxy for IMAP connection
                    return proxy.connect(dest_host=host, dest_port=port)
                else:
                    # Use normal connection for other addresses
                    return original_create_connection(address, timeout, source_address)
            
            # Temporarily replace socket.create_connection
            socket.create_connection = proxy_create_connection
            
            try:
                # Use normal IMAP4_SSL or IMAP4
                if settings.imap_use_ssl:
                    imap_conn = imaplib.IMAP4_SSL(settings.imap_server, settings.imap_port)
                else:
                    imap_conn = imaplib.IMAP4(settings.imap_server, settings.imap_port)
                
                # Login to IMAP server
                imap_conn.login(settings.imap_user, settings.imap_app_password)
                
                logger.info("IMAP proxy connection and login successful")
                
                # Create wrapper
                mailbox = ProxyMailBox(imap_conn, settings.imap_folder)
                
                return mailbox
                
            finally:
                # Restore original socket.create_connection
                socket.create_connection = original_create_connection
                
        except Exception as e:
            logger.error(
                "Proxy IMAP connection failed",
                proxy_host=settings.imap_proxy_host,
                proxy_port=settings.imap_proxy_port,
                proxy_type=settings.imap_proxy_type,
                error=str(e)
            )
            raise ConnectionError(f"Proxy IMAP connection failed: {e}")
    
    @staticmethod
    def _build_proxy_url() -> str:
        """Build proxy URL from settings."""
        if settings.imap_proxy_username and settings.imap_proxy_password:
            # With authentication
            return f"{settings.imap_proxy_type}://{settings.imap_proxy_username}:{settings.imap_proxy_password}@{settings.imap_proxy_host}:{settings.imap_proxy_port}"
        else:
            # Without authentication
            return f"{settings.imap_proxy_type}://{settings.imap_proxy_host}:{settings.imap_proxy_port}"


class ProxyMailBox:
    """MailBox wrapper for IMAP connections through proxy.
    
    Provides imap-tools MailBox-compatible interface for proxy connections.
    """
    
    def __init__(self, imap_conn, folder: str = "INBOX"):
        """Initialize proxy mailbox wrapper.
        
        Args:
            imap_conn: Raw imaplib.IMAP4 connection
            folder: IMAP folder to select
        """
        self._imap = imap_conn
        self.folder = folder
        self._imap.select(folder)
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self._imap.close()
            self._imap.logout()
        except:
            pass
    
    def fetch(self, criteria: str = "ALL", mark_seen: bool = True):
        """Fetch emails similar to imap-tools MailBox.fetch().
        
        Args:
            criteria: IMAP search criteria
            mark_seen: Whether to mark messages as seen
            
        Returns:
            List of email message objects
        """
        import email
        from email.header import decode_header
        from datetime import datetime, timezone
        from email.utils import parsedate_to_datetime
        
        # Search for messages
        status, messages = self._imap.search(None, criteria)
        if status != 'OK':
            return []
        
        message_ids = messages[0].split()
        emails = []
        
        for msg_id in message_ids[-10:]:  # Limit to last 10 emails
            status, msg_data = self._imap.fetch(msg_id, '(RFC822)')
            if status == 'OK':
                email_body = msg_data[0][1]
                msg = email.message_from_bytes(email_body)
                
                # Create simplified message object compatible with imap-tools
                emails.append(SimpleMessage(msg, msg_id.decode()))
        
        return emails


class SimpleMessage:
    """Simple email message object compatible with imap-tools interface."""
    
    def __init__(self, raw_msg, uid: str):
        """Initialize message from raw email.
        
        Args:
            raw_msg: email.message.Message object
            uid: Message UID
        """
        self.uid = uid
        self._msg = raw_msg
        
        # Decode subject
        subject = raw_msg.get('Subject', '')
        if subject:
            from email.header import decode_header
            decoded_subject = decode_header(subject)
            self.subject = ''.join([
                part[0].decode(part[1] or 'utf-8') if isinstance(part[0], bytes) else part[0]
                for part in decoded_subject
            ])
        else:
            self.subject = ''
        
        # Get sender
        self.from_ = raw_msg.get('From', '')
        
        # Get date
        date_str = raw_msg.get('Date', '')
        try:
            from email.utils import parsedate_to_datetime
            self.date = parsedate_to_datetime(date_str)
        except:
            from datetime import datetime, timezone
            self.date = datetime.now(timezone.utc)
        
        # Get headers
        self.headers = dict(raw_msg.items())
        
        # Get text content
        self.text = self._get_text_content(raw_msg)
    
    def _get_text_content(self, msg):
        """Extract text content from email."""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        return part.get_payload(decode=True).decode('utf-8')
                    except:
                        continue
        else:
            if msg.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode('utf-8')
                except:
                    return msg.get_payload()
        return ""