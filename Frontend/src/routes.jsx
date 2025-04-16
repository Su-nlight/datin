import React, { lazy } from 'react';


const Dashboard = lazy(() => import('./components/Dashboard').then(module => ({
  default: module.default
})));

const routes = [
  {
    path: '/dashboard',
    element: <Dashboard />
  }
];

export default routes;
