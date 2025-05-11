import { backendUrl } from '../config';

const response = await fetch(
  `${backendUrl}/api/detections?skip=${skip}&limit=${limit}`
); 