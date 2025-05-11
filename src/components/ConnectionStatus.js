import { backendUrl } from '../config';

const response = await fetch(
  `${backendUrl}/api/device_status`,
  {
    headers: {
      'Accept': 'application/json',
    },
    mode: 'cors',
  }
); 