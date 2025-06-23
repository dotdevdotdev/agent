"""
Monitors system health and performance
"""

import asyncio
import structlog
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

logger = structlog.get_logger()


@dataclass
class HealthMetric:
    name: str
    value: Any
    status: str  # healthy, warning, critical
    threshold: Optional[float] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass 
class SystemHealth:
    overall_status: str
    metrics: List[HealthMetric]
    last_check: datetime
    uptime_seconds: float
    error_rate: float
    active_jobs: int


class HealthMonitor:
    """Monitors system health and detects issues"""

    def __init__(self, github_client=None, job_manager=None):
        self.github_client = github_client
        self.job_manager = job_manager
        self.start_time = datetime.now()
        self.health_history: List[SystemHealth] = []
        self.alert_thresholds = {
            'error_rate': 0.1,  # 10% error rate
            'response_time': 5.0,  # 5 seconds
            'active_jobs': 50,  # 50 concurrent jobs
            'memory_usage': 0.85,  # 85% memory usage
            'api_rate_limit': 0.9  # 90% of rate limit
        }

    async def check_github_api_health(self) -> Dict[str, Any]:
        """Check GitHub API connectivity and rate limits"""
        health_data = {
            'status': 'unknown',
            'rate_limit_remaining': 0,
            'rate_limit_reset': None,
            'response_time': 0,
            'last_error': None
        }

        if not self.github_client:
            health_data['status'] = 'disabled'
            return health_data

        try:
            start_time = datetime.now()
            
            # Simple API call to check connectivity
            await self.github_client._make_request("GET", "https://api.github.com/rate_limit")
            
            response_time = (datetime.now() - start_time).total_seconds()
            
            health_data.update({
                'status': 'healthy',
                'rate_limit_remaining': self.github_client.rate_limit_remaining,
                'rate_limit_reset': self.github_client.rate_limit_reset,
                'response_time': response_time
            })

            # Check if approaching rate limit
            if self.github_client.rate_limit_remaining < 100:
                health_data['status'] = 'warning'
            elif self.github_client.rate_limit_remaining < 10:
                health_data['status'] = 'critical'

        except Exception as e:
            health_data.update({
                'status': 'critical',
                'last_error': str(e)
            })
            logger.error("GitHub API health check failed", error=str(e))

        return health_data

    async def check_job_processing_health(self) -> Dict[str, Any]:
        """Check job processing performance and queue health"""
        health_data = {
            'status': 'unknown',
            'active_jobs': 0,
            'pending_jobs': 0,
            'completed_jobs_24h': 0,
            'failed_jobs_24h': 0,
            'avg_processing_time': 0,
            'queue_depth': 0
        }

        if not self.job_manager:
            health_data['status'] = 'disabled'
            return health_data

        try:
            # Get job statistics
            all_jobs = await self.job_manager.list_jobs(limit=1000)
            
            now = datetime.now()
            yesterday = now - timedelta(hours=24)
            
            active_jobs = [j for j in all_jobs if j.status == 'running']
            pending_jobs = [j for j in all_jobs if j.status == 'pending']
            
            recent_jobs = [j for j in all_jobs if j.created_at >= yesterday]
            completed_recent = [j for j in recent_jobs if j.status == 'completed']
            failed_recent = [j for j in recent_jobs if j.status == 'failed']

            # Calculate average processing time
            processing_times = []
            for job in completed_recent:
                if job.completed_at and job.started_at:
                    duration = (job.completed_at - job.started_at).total_seconds()
                    processing_times.append(duration)

            avg_time = sum(processing_times) / len(processing_times) if processing_times else 0

            health_data.update({
                'active_jobs': len(active_jobs),
                'pending_jobs': len(pending_jobs),
                'completed_jobs_24h': len(completed_recent),
                'failed_jobs_24h': len(failed_recent),
                'avg_processing_time': avg_time,
                'queue_depth': len(pending_jobs)
            })

            # Determine health status
            if len(active_jobs) > self.alert_thresholds['active_jobs']:
                health_data['status'] = 'warning'
            elif len(failed_recent) > len(completed_recent) * 0.5:  # >50% failure rate
                health_data['status'] = 'critical'
            else:
                health_data['status'] = 'healthy'

        except Exception as e:
            health_data.update({
                'status': 'critical',
                'error': str(e)
            })
            logger.error("Job processing health check failed", error=str(e))

        return health_data

    async def check_system_resources(self) -> Dict[str, Any]:
        """Check system resource usage"""
        import psutil
        
        health_data = {
            'status': 'healthy',
            'cpu_percent': 0,
            'memory_percent': 0,
            'disk_percent': 0,
            'load_average': 0
        }

        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent / 100
            
            # Disk usage
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent / 100
            
            # Load average (Unix only)
            try:
                load_avg = psutil.getloadavg()[0]  # 1-minute load average
            except AttributeError:
                load_avg = 0  # Windows doesn't have load average

            health_data.update({
                'cpu_percent': cpu_percent,
                'memory_percent': memory_percent,
                'disk_percent': disk_percent,
                'load_average': load_avg
            })

            # Determine status
            if memory_percent > self.alert_thresholds['memory_usage']:
                health_data['status'] = 'critical'
            elif cpu_percent > 90 or disk_percent > 0.9:
                health_data['status'] = 'warning'

        except Exception as e:
            health_data.update({
                'status': 'critical',
                'error': str(e)
            })
            logger.error("System resource check failed", error=str(e))

        return health_data

    async def generate_health_report(self) -> SystemHealth:
        """Generate comprehensive system health report"""
        
        # Run all health checks
        github_health = await self.check_github_api_health()
        job_health = await self.check_job_processing_health()
        system_health = await self.check_system_resources()

        # Calculate uptime
        uptime = (datetime.now() - self.start_time).total_seconds()

        # Calculate error rate
        error_rate = 0
        if job_health.get('completed_jobs_24h', 0) + job_health.get('failed_jobs_24h', 0) > 0:
            total_jobs = job_health['completed_jobs_24h'] + job_health['failed_jobs_24h']
            error_rate = job_health['failed_jobs_24h'] / total_jobs

        # Create health metrics
        metrics = [
            HealthMetric(
                "github_api_status", 
                github_health['status'], 
                github_health['status']
            ),
            HealthMetric(
                "github_rate_limit", 
                github_health.get('rate_limit_remaining', 0),
                'healthy' if github_health.get('rate_limit_remaining', 0) > 100 else 'warning'
            ),
            HealthMetric(
                "active_jobs", 
                job_health.get('active_jobs', 0),
                'healthy' if job_health.get('active_jobs', 0) < 20 else 'warning'
            ),
            HealthMetric(
                "error_rate", 
                error_rate,
                'healthy' if error_rate < 0.1 else 'critical'
            ),
            HealthMetric(
                "memory_usage", 
                system_health.get('memory_percent', 0),
                'healthy' if system_health.get('memory_percent', 0) < 0.8 else 'warning'
            ),
            HealthMetric(
                "avg_processing_time", 
                job_health.get('avg_processing_time', 0),
                'healthy' if job_health.get('avg_processing_time', 0) < 300 else 'warning'
            )
        ]

        # Determine overall status
        statuses = [m.status for m in metrics]
        if 'critical' in statuses:
            overall_status = 'critical'
        elif 'warning' in statuses:
            overall_status = 'warning'
        else:
            overall_status = 'healthy'

        health_report = SystemHealth(
            overall_status=overall_status,
            metrics=metrics,
            last_check=datetime.now(),
            uptime_seconds=uptime,
            error_rate=error_rate,
            active_jobs=job_health.get('active_jobs', 0)
        )

        # Store in history (keep last 100 reports)
        self.health_history.append(health_report)
        if len(self.health_history) > 100:
            self.health_history = self.health_history[-100:]

        logger.info(
            "Health report generated",
            overall_status=overall_status,
            error_rate=error_rate,
            active_jobs=job_health.get('active_jobs', 0)
        )

        return health_report

    async def detect_anomalies(self) -> List[Dict[str, Any]]:
        """Detect system anomalies and performance issues"""
        anomalies = []

        if len(self.health_history) < 10:
            return anomalies  # Need more data

        # Get recent health reports
        recent_reports = self.health_history[-10:]
        
        # Check for error rate spike
        recent_error_rates = [r.error_rate for r in recent_reports]
        avg_error_rate = sum(recent_error_rates) / len(recent_error_rates)
        
        if avg_error_rate > self.alert_thresholds['error_rate']:
            anomalies.append({
                'type': 'error_rate_spike',
                'severity': 'high',
                'value': avg_error_rate,
                'threshold': self.alert_thresholds['error_rate'],
                'description': f"Error rate {avg_error_rate:.1%} exceeds threshold {self.alert_thresholds['error_rate']:.1%}"
            })

        # Check for job queue buildup
        recent_active_jobs = []
        for report in recent_reports:
            active_jobs_metric = next((m for m in report.metrics if m.name == 'active_jobs'), None)
            if active_jobs_metric:
                recent_active_jobs.append(active_jobs_metric.value)

        if recent_active_jobs:
            avg_active_jobs = sum(recent_active_jobs) / len(recent_active_jobs)
            if avg_active_jobs > self.alert_thresholds['active_jobs']:
                anomalies.append({
                    'type': 'job_queue_buildup',
                    'severity': 'medium',
                    'value': avg_active_jobs,
                    'threshold': self.alert_thresholds['active_jobs'],
                    'description': f"Average active jobs {avg_active_jobs:.0f} exceeds threshold {self.alert_thresholds['active_jobs']}"
                })

        # Check for memory usage trend
        recent_memory = []
        for report in recent_reports:
            memory_metric = next((m for m in report.metrics if m.name == 'memory_usage'), None)
            if memory_metric:
                recent_memory.append(memory_metric.value)

        if len(recent_memory) >= 5:
            # Check if memory usage is trending upward
            if recent_memory[-1] > recent_memory[0] * 1.2:  # 20% increase
                anomalies.append({
                    'type': 'memory_trend',
                    'severity': 'medium',
                    'value': recent_memory[-1],
                    'description': f"Memory usage trending upward: {recent_memory[-1]:.1%}"
                })

        return anomalies

    def get_health_summary(self) -> Dict[str, Any]:
        """Get summary of current health status"""
        if not self.health_history:
            return {'status': 'unknown', 'message': 'No health data available'}

        latest_report = self.health_history[-1]
        
        return {
            'status': latest_report.overall_status,
            'uptime_hours': latest_report.uptime_seconds / 3600,
            'error_rate': latest_report.error_rate,
            'active_jobs': latest_report.active_jobs,
            'last_check': latest_report.last_check.isoformat(),
            'metrics_count': len(latest_report.metrics),
            'healthy_metrics': len([m for m in latest_report.metrics if m.status == 'healthy']),
            'warning_metrics': len([m for m in latest_report.metrics if m.status == 'warning']),
            'critical_metrics': len([m for m in latest_report.metrics if m.status == 'critical'])
        }