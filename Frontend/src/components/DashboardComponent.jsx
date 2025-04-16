import React, { useState, useEffect } from 'react';
import './DashboardStyles.css';

const DashboardComponent = () => {
  const [feedbackEmail, setFeedbackEmail] = useState('');
  const [feedbackContent, setFeedbackContent] = useState('');
  const [logSubmissions, setLogSubmissions] = useState(78); 
  const [heatmapData, setHeatmapData] = useState([]);
  const [showProfileDropdown, setShowProfileDropdown] = useState(false);

  useEffect(() => {
    const generateHeatmapData = () => {
      const data = [];
      const today = new Date();
      
      for (let i = 0; i < 365; i++) {
        const date = new Date(today);
        date.setDate(date.getDate() - i);
        
        data.push({
          date: date.toISOString().split('T')[0],
          count: Math.floor(Math.random() * 5) 
        });
      }
      
      return data.reverse(); 
    };
    
    setHeatmapData(generateHeatmapData());

    const handleClickOutside = (event) => {
      if (showProfileDropdown && !event.target.closest('.header-profile')) {
        setShowProfileDropdown(false);
      }
    };

    document.addEventListener('click', handleClickOutside);
    return () => {
      document.removeEventListener('click', handleClickOutside);
    };
  }, [showProfileDropdown]);

  const handleFeedbackSubmit = (e) => {
    e.preventDefault();
    console.log("Feedback submitted:", { feedbackEmail, feedbackContent });
    setFeedbackEmail('');
    setFeedbackContent('');
    alert("Thank you for your feedback!");
  };

  const handleProfileClick = () => {
    setShowProfileDropdown(!showProfileDropdown);
  };

  const handleMenuItemClick = (option) => {
    console.log(`Navigating to: ${option}`);
    setShowProfileDropdown(false);
    
  };

  const renderHeatmap = () => {
    const weeks = [];
    let currentWeek = [];
    
    for (let i = 0; i < heatmapData.length; i++) {
      if (i % 7 === 0 && i !== 0) {
        weeks.push(currentWeek);
        currentWeek = [];
      }
      currentWeek.push(heatmapData[i]);
    }
    
    if (currentWeek.length > 0) {
      weeks.push(currentWeek);
    }
    
    return (
      <div className="heatmap-container">
        {weeks.map((week, weekIdx) => (
          <div key={`week-${weekIdx}`} className="heatmap-week">
            {week.map((day, dayIdx) => (
              <div 
                key={`day-${weekIdx}-${dayIdx}`} 
                className={`heatmap-day level-${day.count}`}
                title={`${day.date}: ${day.count} activities`}
              />
            ))}
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <div className="logo-container">
          <div className="logo">
            <span className="gradient-text">DATIN</span>
          </div>
        </div>
        <div className="header-title">Dashboard</div>
        <div className="header-profile">
          <div className="profile-icon" onClick={handleProfileClick}></div>
          {showProfileDropdown && (
            <div className="profile-dropdown">
              <div 
                className="dropdown-item" 
                onClick={() => handleMenuItemClick('Chat Interface')}
              >
                Chat Interface
              </div>
              <div 
                className="dropdown-item" 
                onClick={() => handleMenuItemClick('Log Submit')}
              >
                Log Submit
              </div>
            </div>
          )}
        </div>
      </div>
      
      <div className="dashboard-content">
        <div className="sidebar">
          <div className="sidebar-section">
            <div className="sidebar-item active">Chat History</div>
          </div>
          
          <div className="sidebar-section">
            <div className="sidebar-item">Threat Report Submitted History</div>
          </div>
        </div>
        
        <div className="main-content">
          <div className="dashboard-row">
            <div className="dashboard-card threat-heatmap">
              <h3>Threat Report Heatmap</h3>
              {renderHeatmap()}
            </div>
            
            <div className="dashboard-card listing-verification">
              <h3>Listing for Verification</h3>
              <div className="verification-content">
                <div className="verification-stat">
                  <div className="stat-number">{logSubmissions}</div>
                  <div className="stat-label">Total Logs Submitted for Verification</div>
                </div>
                <div className="verification-chart">
                  <div className="chart-bar" style={{ height: '75%' }}></div>
                  <div className="chart-bar" style={{ height: '45%' }}></div>
                  <div className="chart-bar" style={{ height: '90%' }}></div>
                  <div className="chart-bar" style={{ height: '60%' }}></div>
                  <div className="chart-bar" style={{ height: '30%' }}></div>
                </div>
              </div>
            </div>
          </div>
          
          <div className="dashboard-row">
            <div className="dashboard-card suggestions-open">
              <h3>Suggestions Open</h3>
              <form onSubmit={handleFeedbackSubmit} className="feedback-form">
                <div className="form-group">
                  <label htmlFor="email">Email</label>
                  <input 
                    type="email" 
                    id="email" 
                    value={feedbackEmail}
                    onChange={(e) => setFeedbackEmail(e.target.value)} 
                    placeholder="Enter your email"
                    required
                  />
                </div>
                
                <div className="form-group">
                  <label htmlFor="feedback">Feedback (Max 300 characters)</label>
                  <textarea 
                    id="feedback" 
                    value={feedbackContent}
                    onChange={(e) => {
                      if (e.target.value.length <= 300) {
                        setFeedbackContent(e.target.value)
                      }
                    }}
                    placeholder="Enter your feedback here"
                    maxLength={300}
                    required
                  ></textarea>
                  <div className="character-count">
                    {feedbackContent.length}/300 characters
                  </div>
                </div>
                
                <button type="submit" className="submit-btn">Submit Feedback</button>
              </form>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DashboardComponent;