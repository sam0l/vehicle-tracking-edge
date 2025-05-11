import { backendUrl } from '../config';

const response = await fetch(
  `${backendUrl}/api/detections?limit=1`,
  {
    headers: {
      'Accept': 'application/json',
    },
    mode: 'cors',
  }
); 