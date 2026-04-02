import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    # Auth
    username: str = field(default_factory=lambda: os.getenv("LMS_USERNAME", ""))
    password: str = field(default_factory=lambda: os.getenv("LMS_PASSWORD", ""))
    
    # Modes
    headless: bool = True
    dry_run: bool = False
    
    # URLs
    login_url: str = field(default_factory=lambda: os.getenv("LMS_LOGIN_URL", "https://adamasknowledgecity.ac.in/student/login"))
    
    # Browser Config
    timeout_ms: int = 30000
    navigation_timeout_ms: int = 60000
    
    # Logic Config
    max_retries: int = 3

    def validate_credentials(self) -> bool:
        return bool(self.username and self.password)
