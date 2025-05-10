from flask import Flask, jsonify, request
from flask_cors import CORS
import logging
import yaml
import time
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Load configuration
with open('config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Setup logging
logging.basicConfig(
    level=getattr(logging, config['logging']['level']),
    format=config['logging']['format'],
    handlers=[
        logging.FileHandler('backend.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# In-memory storage for SIM data (in production, use a database)
sim_data = {
    'balance': None,
    'consumption': {
        'current_rate': 0,
        'total_bytes': 0,
        'last_update': None
    }
}

@app.route('/api/sim-data', methods=['GET'])
def get_sim_data():
    """Get current SIM data balance."""
    return jsonify(sim_data['balance'] if sim_data['balance'] else {'error': 'No data available'})

@app.route('/api/data-consumption', methods=['GET'])
def get_data_consumption():
    """Get current data consumption statistics."""
    return jsonify(sim_data['consumption'])

@app.route('/api/sim-data', methods=['POST'])
def update_sim_data():
    """Update SIM data from edge device."""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        sim_data['balance'] = {
            'balance': data.get('balance'),
            'unit': data.get('unit'),
            'timestamp': data.get('timestamp', int(time.time()))
        }
        logger.info(f"Updated SIM data: {sim_data['balance']}")
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error updating SIM data: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/data-consumption', methods=['POST'])
def update_data_consumption():
    """Update data consumption statistics from edge device."""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        sim_data['consumption'] = {
            'current_rate': data.get('current_rate', 0),
            'total_bytes': data.get('total_bytes', 0),
            'last_update': int(time.time())
        }
        logger.info(f"Updated data consumption: {sim_data['consumption']}")
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error updating data consumption: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=config['api']['port']) 