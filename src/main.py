from src.sim_monitor import SimMonitor

class VehicleTracker:
    def __init__(self, config_path="config/config.yaml"):
        self.sim_monitor = SimMonitor(
            port=config['sim']['port'],
            baudrate=config['sim']['baudrate']
        )

    def run(self):
        try:
            while True:
                # Check SIM data balance periodically
                sim_data = self.sim_monitor.get_data_balance()
                if sim_data:
                    self.send_sim_data(sim_data)
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
        finally:
            self.cleanup()

    def send_sim_data(self, sim_data):
        """Send SIM data to backend."""
        try:
            url = f"{self.config['backend']['url']}{self.config['backend']['endpoint_prefix']}{self.config['backend']['sim_data_endpoint']}"
            response = requests.post(url, json=sim_data)
            response.raise_for_status()
            self.logger.info(f"Sent SIM data to backend: {sim_data}")
        except Exception as e:
            self.logger.error(f"Failed to send SIM data: {e}")
            self.save_offline_data('sim_data', sim_data)

    def cleanup(self):
        """Cleanup resources."""
        if hasattr(self, 'sim_monitor'):
            self.sim_monitor.close() 