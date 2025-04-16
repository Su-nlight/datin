import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import './ChatInterface.css';

const ChatInterface = () => {
  const [message, setMessage] = useState('');
  const [showDropdown, setShowDropdown] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate(); 
  
  const chatHistory = [
    { id: 1, title: 'XYZ' },
    { id: 2, title: 'ABC' },
    { id: 3, title: 'XYZ' },
  ];

  const threatReports = [
    { id: 1, title: 'Network Intrusion Report' },
    { id: 2, title: 'Ransomware Analysis' },
    { id: 3, title: 'DDoS Attack Patterns' },
  ];
  
  const initialMessages = [
    {
      id: 1,
      sender: 'ai',
      content: 'Welcome to DATIN - Decentralized AI Threat Intelligence Network. How can I assist with your cybersecurity inquiry today?',
      time: `${new Date().getHours()}:${new Date().getMinutes()}`
    },
  ];
  
  const [messages, setMessages] = useState(initialMessages);
  
  const handleSendMessage = async (e) => {
    e.preventDefault();
    
    if (message.trim()) {
      // Create and add user message to chat
      const newMessage = {
        id: messages.length + 1,
        sender: 'user',
        content: message,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      
      setMessages([...messages, newMessage]);
      
      // Show loading state
      setIsLoading(true);
      
      try {
        // Send POST request to the endpoint
        const response = await axios.post('http://127.0.0.1:8000/query', {
          query: message
        });
        
        // Extract data from nested JSON response
        const responseData = response.data;
        
        if (responseData && responseData.messages && responseData.query_resp) {
          // Unpack the nested JSON response
          const { messages: responseMessages, query_resp } = responseData;
          
          // Create AI response message
          const aiResponse = {
            id: messages.length + 2,
            sender: 'ai',
            content: responseMessages || query_resp || 'I received your query, but there was an issue processing it.',
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          };
          
          setMessages(prev => [...prev, aiResponse]);
          
          // You can also handle the query_resp data specifically if needed
          console.log('Full query response:', query_resp);
        } else {
          // Handle unexpected response structure
          const aiResponse = {
            id: messages.length + 2,
            sender: 'ai',
            content: 'I received your query, but the response format was unexpected.',
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          };
          
          setMessages(prev => [...prev, aiResponse]);
        }
      } catch (error) {
        console.error('Error sending query:', error);
        
        // Handle error in UI
        const errorMessage = {
          id: messages.length + 2,
          sender: 'ai',
          content: 'Sorry, there was an error processing your request. Please try again later.',
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        };
        
        setMessages(prev => [...prev, errorMessage]);
      } finally {
        // Clear input and loading state
        setMessage('');
        setIsLoading(false);
      }
    }
  };

  const toggleDropdown = () => {
    setShowDropdown(!showDropdown);
  };
  
  const handleNavigation = (page) => {
    if (page === 'Dashboard') {
      navigate('/'); 
    } else if (page === 'LogSubmit') {
      navigate('/submit-report'); 
    }
    
    setShowDropdown(false);
  };
  
  return (
    <div className="chat-app">
      <div className="header">
        <div className="logo">
          <span className="gradient-text">DATIN</span>
        </div>
        <div className="profile-container">
          <div className="profile-icon" onClick={toggleDropdown}>
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
              <circle cx="12" cy="7" r="4"></circle>
            </svg>
          </div>
          {showDropdown && (
            <div className="dropdown-menu">
              <div className="dropdown-item" onClick={() => handleNavigation('Dashboard')}>
                Home
              </div>
              <div className="dropdown-item" onClick={() => handleNavigation('LogSubmit')}>
                Log Submit
              </div>
            </div>
          )}
        </div>
      </div>
      
      <div className="chat-container">
        <div className="sidebar">
          <div className="chat-history">
            <h3 className="section-title">Chat History</h3>
            {chatHistory.map(chat => (
              <div key={chat.id} className="history-item">
                <div className="history-icon">
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="12 6 12 12 16 14"></polyline>
                  </svg>
                </div>
                <div className="history-text">{chat.title}</div>
              </div>
            ))}
          </div>
          
          <div className="threat-report">
            <h3 className="section-title">Threat Report History</h3>
            {threatReports.map(report => (
              <div key={report.id} className="history-item">
                <div className="history-icon">
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                    <polyline points="13 2 13 9 20 9"></polyline>
                  </svg>
                </div>
                <div className="history-text">{report.title}</div>
              </div>
            ))}
          </div>
        </div>
        
        <div className="main-content">
          <div className="chat-header">
            <div className="chat-title">AI Threat Intelligence Assistant</div>
            <div className="chat-actions">
              {/* Additional actions can go here */}
            </div>
          </div>
          
          <div className="messages-container">
            {messages.map(msg => (
              <div key={msg.id} className={`message message-${msg.sender}`}>
                <div className="message-content">
                  {msg.content}
                </div>
                <div className="message-info">
                  {msg.sender === 'user' ? 'You' : 'AI Assistant'} • {msg.time}
                </div>
              </div>
            ))}
            {isLoading && (
              <div className="message message-ai loading">
                <div className="message-content">
                  <span className="loading-dot"></span>
                  <span className="loading-dot"></span>
                  <span className="loading-dot"></span>
                </div>
              </div>
            )}
          </div>
          
          <form className="input-area" onSubmit={handleSendMessage}>
            <input 
              type="text" 
              className="message-input" 
              placeholder="Ask a security question..." 
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              disabled={isLoading}
            />
            <button type="submit" className="send-btn" disabled={isLoading}>
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
              </svg>
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default ChatInterface;