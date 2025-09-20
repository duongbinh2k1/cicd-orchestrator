"""Mock data loader utility."""

import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

import structlog

logger = structlog.get_logger(__name__)

class MockDataLoader:
    """Utility class to load and manage mock data from JSON files."""
    
    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize mock data loader.
        
        Args:
            data_dir: Directory containing mock data files. Defaults to data/mock.
        """
        if data_dir is None:
            # Get project root and construct path to data/mock
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent.parent
            data_dir = project_root / "data" / "mock"
            
        self.data_dir = Path(data_dir)
        self._cache: Dict[str, Any] = {}
        
        logger.debug("MockDataLoader initialized", data_dir=str(self.data_dir))
    
    def _load_json_file(self, filename: str) -> Dict[str, Any]:
        """Load JSON data from file with caching.
        
        Args:
            filename: Name of JSON file to load
            
        Returns:
            Loaded JSON data
        """
        if filename in self._cache:
            return self._cache[filename]
            
        file_path = self.data_dir / filename
        if not file_path.exists():
            logger.error("Mock data file not found", file=str(file_path))
            return {}
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._cache[filename] = data
                logger.debug("Loaded mock data file", file=filename, scenarios=len(data))
                return data
        except Exception as e:
            logger.error("Failed to load mock data file", file=filename, error=str(e))
            return {}
    
    def get_scenario(self, scenario_type: str, scenario_name: str) -> Dict[str, Any]:
        """Get a specific test scenario.
        
        Args:
            scenario_type: Type of scenario file (e.g., 'pipeline', 'test', 'deployment')
            scenario_name: Name of the specific scenario
            
        Returns:
            Scenario data with dynamic timestamps
        """
        filename = f"{scenario_type}_scenarios.json"
        data = self._load_json_file(filename)
        
        if scenario_name not in data:
            logger.warning("Scenario not found", type=scenario_type, name=scenario_name)
            return {}
            
        scenario = data[scenario_name].copy()
        
        # Add dynamic timestamps
        now = datetime.now(timezone.utc)
        self._add_dynamic_timestamps(scenario.get('webhook', {}), now)
        
        return scenario
    
    def get_base_data(self, data_type: str) -> List[Dict[str, Any]]:
        """Get base data like projects, users, runners.
        
        Args:
            data_type: Type of base data ('projects', 'users', 'runners')
            
        Returns:
            List of base data items
        """
        data = self._load_json_file("base_data.json")
        return data.get(data_type, [])
    
    def _add_dynamic_timestamps(self, webhook_data: Dict[str, Any], base_time: datetime) -> None:
        """Add dynamic timestamps to webhook data.
        
        Args:
            webhook_data: Webhook data to modify
            base_time: Base time for generating timestamps
        """
        # Add timestamps to object_attributes
        if 'object_attributes' in webhook_data:
            attrs = webhook_data['object_attributes']
            attrs['created_at'] = base_time.isoformat()
            attrs['finished_at'] = base_time.isoformat()
        
        # Add timestamps to commit
        if 'commit' in webhook_data:
            webhook_data['commit']['timestamp'] = base_time.isoformat()
        
        # Add timestamps to builds
        if 'builds' in webhook_data:
            for build in webhook_data['builds']:
                build['created_at'] = base_time.isoformat()
                build['started_at'] = base_time.isoformat()
                build['finished_at'] = base_time.isoformat()
    
    def create_custom_webhook(self, 
                            project_id: int,
                            pipeline_status: str = "failed",
                            job_name: str = "test",
                            branch: str = "main",
                            commit_message: str = "Test commit",
                            include_logs: bool = True) -> Dict[str, Any]:
        """Create a custom webhook payload.
        
        Args:
            project_id: Project ID
            pipeline_status: Pipeline status
            job_name: Job name
            branch: Branch name
            commit_message: Commit message
            include_logs: Whether to include sample logs
            
        Returns:
            Custom webhook payload
        """
        # Get base project data
        projects = self.get_base_data('projects')
        project = next((p for p in projects if p['id'] == project_id), None)
        
        if not project:
            # Create default project
            project = {
                "id": project_id,
                "name": f"project-{project_id}",
                "path_with_namespace": f"test/project-{project_id}",
                "web_url": f"https://gitlab.com/test/project-{project_id}",
                "default_branch": "main"
            }
        
        # Generate random IDs
        pipeline_id = random.randint(600000, 700000)
        job_id = random.randint(6000000, 7000000)
        commit_sha = ''.join(random.choices('0123456789abcdef', k=40))
        
        now = datetime.now(timezone.utc)
        
        # Sample logs based on job name and status
        trace = ""
        if include_logs and pipeline_status == "failed":
            if "test" in job_name.lower():
                trace = "$ python -m pytest\nE   AssertionError: Expected result not found\nFAILED tests/test_example.py::test_function - AssertionError\n=== 1 failed in 2.3s ==="
            elif "build" in job_name.lower():
                trace = "$ npm install\nnpm ERR! Failed to resolve dependency\nERROR: Build failed with exit code 1"
            else:
                trace = f"$ {job_name}\nERROR: Command failed with exit code 1"
        
        return {
            "object_kind": "Pipeline Hook",
            "object_attributes": {
                "id": pipeline_id,
                "ref": branch,
                "tag": False,
                "sha": commit_sha,
                "status": pipeline_status,
                "created_at": now.isoformat(),
                "finished_at": now.isoformat(),
                "duration": random.randint(30, 300),
                "stages": ["build", "test", "deploy"]
            },
            "project": project,
            "commit": {
                "id": commit_sha,
                "message": commit_message,
                "timestamp": now.isoformat(),
                "author": {
                    "name": "Test User",
                    "email": "test@example.com"
                }
            },
            "builds": [
                {
                    "id": job_id,
                    "name": job_name,
                    "status": pipeline_status,
                    "stage": "test",
                    "created_at": now.isoformat(),
                    "started_at": now.isoformat(),
                    "finished_at": now.isoformat(),
                    "trace": trace,
                    "web_url": f"{project['web_url']}/-/jobs/{job_id}",
                    "project": {
                        "id": project["id"],
                        "name": project["name"],
                        "web_url": project["web_url"]
                    }
                }
            ]
        }
    
    def list_available_scenarios(self) -> Dict[str, List[str]]:
        """List all available scenarios.
        
        Returns:
            Dictionary mapping scenario types to scenario names
        """
        scenarios = {}
        
        scenario_files = [
            ("pipeline", "pipeline_scenarios.json"),
            ("test", "test_scenarios.json"),
            ("deployment", "deployment_scenarios.json")
        ]
        
        for scenario_type, filename in scenario_files:
            data = self._load_json_file(filename)
            scenarios[scenario_type] = list(data.keys())
        
        return scenarios
    
    def clear_cache(self) -> None:
        """Clear the internal cache."""
        self._cache.clear()
        logger.debug("Mock data cache cleared")


# Global instance
mock_loader = MockDataLoader()