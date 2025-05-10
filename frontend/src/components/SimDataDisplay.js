import React, { useState, useEffect } from 'react';
import { Card, Typography, CircularProgress, Box, LinearProgress } from '@mui/material';
import { styled } from '@mui/material/styles';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import DataUsageIcon from '@mui/icons-material/DataUsage';
import SpeedIcon from '@mui/icons-material/Speed';

const StyledCard = styled(Card)(({ theme }) => ({
  padding: theme.spacing(2),
  margin: theme.spacing(2),
  backgroundColor: theme.palette.background.paper,
  borderRadius: theme.spacing(1),
  boxShadow: theme.shadows[2],
}));

const DataContainer = styled('div')({
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  marginTop: '8px',
});

const RateContainer = styled('div')({
  display: 'flex',
  alignItems: 'center',
  gap: '8px',
  marginTop: '16px',
});

const formatBytes = (bytes) => {
  if (bytes === 0) return '0 B/s';
  const k = 1024;
  const sizes = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
};

const formatTotalBytes = (bytes) => {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
};

const SimDataDisplay = () => {
  const [simData, setSimData] = useState(null);
  const [consumption, setConsumption] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = async () => {
    try {
      const [balanceResponse, consumptionResponse] = await Promise.all([
        fetch('/api/sim-data'),
        fetch('/api/data-consumption')
      ]);

      if (!balanceResponse.ok || !consumptionResponse.ok) {
        throw new Error('Failed to fetch data');
      }

      const balanceData = await balanceResponse.json();
      const consumptionData = await consumptionResponse.json();

      setSimData(balanceData);
      setConsumption(consumptionData);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // Refresh data every 30 seconds
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <StyledCard>
        <Typography variant="h6">SIM Data</Typography>
        <DataContainer>
          <CircularProgress size={24} />
        </DataContainer>
      </StyledCard>
    );
  }

  if (error) {
    return (
      <StyledCard>
        <Typography variant="h6">SIM Data</Typography>
        <Typography color="error">{error}</Typography>
      </StyledCard>
    );
  }

  return (
    <StyledCard>
      <Typography variant="h6" gutterBottom>
        <DataUsageIcon sx={{ mr: 1, verticalAlign: 'middle' }} />
        SIM Data
      </Typography>
      
      <DataContainer>
        <Typography variant="body1">
          Data Balance:
        </Typography>
        <Typography variant="h6" color="primary">
          {simData ? `${simData.balance} ${simData.unit}` : 'N/A'}
        </Typography>
      </DataContainer>

      {consumption && (
        <>
          <RateContainer>
            <TrendingUpIcon color="action" />
            <Typography variant="body2" color="textSecondary">
              Current Usage Rate:
            </Typography>
            <Typography variant="body2" color="primary">
              {formatBytes(consumption.current_rate)}
            </Typography>
          </RateContainer>

          <RateContainer>
            <SpeedIcon color="action" />
            <Typography variant="body2" color="textSecondary">
              Total Data Used:
            </Typography>
            <Typography variant="body2" color="primary">
              {formatTotalBytes(consumption.total_bytes)}
            </Typography>
          </RateContainer>

          {consumption.current_rate > 0 && (
            <Box sx={{ mt: 2 }}>
              <LinearProgress 
                variant="determinate" 
                value={Math.min((consumption.current_rate / (1024 * 1024)) * 100, 100)} 
                color="primary"
              />
            </Box>
          )}
        </>
      )}

      {simData && (
        <Typography variant="caption" color="textSecondary" sx={{ display: 'block', mt: 1 }}>
          Last updated: {new Date(simData.timestamp * 1000).toLocaleString()}
        </Typography>
      )}
    </StyledCard>
  );
};

export default SimDataDisplay; 