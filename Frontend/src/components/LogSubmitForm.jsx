import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom'; 
import './LogSubmitForm.css';

const LogSubmitForm = () => {
  const [formData, setFormData] = useState({
    owner: '',
    content: '',
    tokenAddress: '',
    reward: ''
  });
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [contentLength, setContentLength] = useState(0);
  const [showDropdown, setShowDropdown] = useState(false);
  const navigate = useNavigate(); 

  const handleChange = (e) => {
    const { name, value } = e.target;
    
    if (name === 'reward' && value !== '') {
      if (!/^\d+$/.test(value)) return;
    }
    
    if (name === 'content') {
      if (value.length > 600) return;
      setContentLength(value.length);
    }

    setFormData({
      ...formData,
      [name]: value
    });
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!formData.owner || !formData.content || !formData.tokenAddress || !formData.reward) {
      alert("All fields are required");
      return;
    }
    
    console.log("Submitting log:", formData);
    setIsSubmitted(true);
    
    setTimeout(() => {
      setIsSubmitted(false);
      setFormData({
        owner: '',
        content: '',
        tokenAddress: '',
        reward: ''
      });
      setContentLength(0);
    }, 3000);
  };

  const toggleDropdown = () => {
    setShowDropdown(!showDropdown);
  };
  
  const handleNavigation = (page) => {
    if (page === 'ChatInterface') {
      navigate('/chat');
    } else if (page === 'Dashboard') {
      navigate('/');
    }
    
    setShowDropdown(false);
  };

  return (
    <div className="log-submit-container">
      <div className="header">
        <div className="datin-logo" onClick={() => navigate('/')}>DATIN</div>
        <div className="header-title">AI Threat Intelligence Assistant</div>
        <div className="profile-container">
          <div className="user-icon" onClick={toggleDropdown}>
            <div className="profile-icon"></div>
          </div>
          {showDropdown && (
            <div className="dropdown-menu">
              <div className="dropdown-item" onClick={() => handleNavigation('ChatInterface')}>
                Chat Interface
              </div>
              <div className="dropdown-item" onClick={() => handleNavigation('Dashboard')}>
                Home
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="content-container">
        <div className="sidebar">
          <div className="sidebar-section">
            <h3 className="section-title">Chat History</h3>
            <div className="chat-history-item">
              <div className="chat-indicator"></div>
              <span>XYZ</span>
            </div>
            <div className="chat-history-item">
              <div className="chat-indicator"></div>
              <span>ABC</span>
            </div>
            <div className="chat-history-item">
              <div className="chat-indicator"></div>
              <span>XYZ</span>
            </div>
          </div>
          
          <div className="sidebar-section">
            <h3 className="section-title">Threat Report History</h3>
            <div className="threat-history-item">
              <div className="file-icon"></div>
              <span>Network Intrusion...</span>
            </div>
            <div className="threat-history-item">
              <div className="file-icon"></div>
              <span>Ransomware...</span>
            </div>
            <div className="threat-history-item">
              <div className="file-icon"></div>
              <span>DDoS Attack...</span>
            </div>
          </div>
        </div>

        <div className="main-content">
          <h2 className="form-title">AI Threat Intelligence Log Submission</h2>
          
          {isSubmitted ? (
            <div className="submission-success">
              <p>Your Log is Submitted</p>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="log-form">
              <div className="form-group">
                <label>Owner:</label>
                <input
                  type="text"
                  name="owner"
                  value={formData.owner}
                  onChange={handleChange}
                  placeholder="owner wallet address"
                  required
                />
              </div>

              <div className="form-group">
                <label>Content:</label>
                <textarea
                  name="content"
                  value={formData.content}
                  onChange={handleChange}
                  placeholder="cyber security content"
                  required
                ></textarea>
                <div className="character-count">{contentLength}/600</div>
              </div>

              <div className="form-group">
                <label>Token Address:</label>
                <input
                  type="text"
                  name="tokenAddress"
                  value={formData.tokenAddress}
                  onChange={handleChange}
                  placeholder="requested token for reward"
                  required
                />
              </div>

              <div className="form-group">
                <label>Reward for Verification:</label>
                <input
                  type="text"
                  name="reward"
                  value={formData.reward}
                  onChange={handleChange}
                  placeholder="enter amount of coins for reward"
                  required
                />
              </div>

              <div className="form-actions">
                <button type="submit" className="submit-button">Submit Report</button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};

export default LogSubmitForm;