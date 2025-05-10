import React, { useState, useEffect } from 'react';
import { Card, Typography, CircularProgress } from '@mui/material';
import { styled } from '@mui/material/styles';

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

const SimDataDisplay = () => {
  const [simData, setSimData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchSimData = async () => {
    try {
      const response = await fetch('/api/sim-data');
      if (!response.ok) {
        throw new Error('Failed to fetch SIM data');
      }
      const data = await response.json();
      setSimData(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSimData();
    // Refresh data every 5 minutes
    const interval = setInterval(fetchSimData, 300000);
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
      <Typography variant="h6">SIM Data</Typography>
      <DataContainer>
        <Typography variant="body1">
          Data Balance:
        </Typography>
        <Typography variant="h6" color="primary">
          {simData ? `${simData.balance} ${simData.unit}` : 'N/A'}
        </Typography>
      </DataContainer>
      {simData && (
        <Typography variant="caption" color="textSecondary">
          Last updated: {new Date(simData.timestamp * 1000).toLocaleString()}
        </Typography>
      )}
    </StyledCard>
  );
};

export default SimDataDisplay; 