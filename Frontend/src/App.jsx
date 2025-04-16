import React, { useState, useEffect, useRef } from 'react';
import { motion, useScroll, useTransform, useInView, useAnimation } from 'framer-motion';
import { BrowserRouter as Router, Routes, Route, Link, useNavigate } from 'react-router-dom';
import './App.css';
import InteractiveCoin from './components/InteractiveCoin.js';
import ChatInterface from './components/ChatInterface.jsx';
import LogSubmitForm from './components/LogSubmitForm.js';


const TypingAnimation = ({ text }) => {
  return (
    <div className="typing-wrapper">
      <h1 className="typing-text">{text}</h1>
    </div>
  );
};

const ScrollDownIndicator = () => {
  return (
    <motion.div 
      className="scroll-down-indicator"
      initial={{ opacity: 0 }}
      animate={{ 
        opacity: [0.2, 1, 0.2], 
        y: [0, 10, 0] 
      }}
      transition={{ 
        duration: 2,
        repeat: Infinity,
        ease: "easeInOut" 
      }}
    >
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <motion.path 
          d="M12 5L12 19M12 19L19 12M12 19L5 12" 
          stroke="var(--primary)" 
          strokeWidth="2" 
          strokeLinecap="round" 
          strokeLinejoin="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ 
            duration: 2,
            repeat: Infinity,
            ease: "easeInOut" 
          }}
        />
      </svg>
    </motion.div>
  );
};

const FeatureCard = ({ icon, title, description, index }) => {
  const ref = useRef(null);
  const isInView = useInView(ref, { once: false, amount: 0.5 });
  
  const variants = {
    hidden: { 
      opacity: 0,
      y: 50,
      scale: 0.9,
      rotateY: 30
    },
    visible: (i) => ({ 
      opacity: 1,
      y: 0,
      scale: 1,
      rotateY: 0,
      transition: { 
        duration: 0.7, 
        delay: i * 0.2,
        type: "spring",
        stiffness: 100
      }
    })
  };

  return (
    <motion.div 
      className="datin-feature-card"
      ref={ref}
      variants={variants}
      initial="hidden"
      animate={isInView ? "visible" : "hidden"}
      custom={index}
      whileHover={{ 
        scale: 1.05, 
        boxShadow: "0 15px 30px rgba(0, 255, 170, 0.2)",
        transition: { duration: 0.3 }
      }}
    >
      <motion.div 
        className="datin-feature-icon"
        animate={isInView ? { 
          scale: [1, 1.2, 1],
          rotate: [0, 5, -5, 0]
        } : {}}
        transition={{ duration: 0.5, delay: index * 0.2 + 0.5 }}
      >
        {icon}
      </motion.div>
      <motion.h3
        animate={isInView ? { 
          background: "linear-gradient(to right, var(--primary), var(--secondary))",
          backgroundClip: "text",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          color: "transparent"
        } : {}}
        transition={{ duration: 0.8, delay: index * 0.2 + 0.7 }}
      >
        {title}
      </motion.h3>
      <p>{description}</p>
    </motion.div>
  );
};

const LoginModal = ({ isOpen, onClose, onSwitchToSignup }) => {
  if (!isOpen) return null;
  
  const handleSubmit = (e) => {
    e.preventDefault();
    console.log('Login attempted');
  };

  return (
    <div className="datin-modal-overlay" onClick={onClose}>
      <motion.div 
        className="datin-modal" 
        onClick={(e) => e.stopPropagation()}
        initial={{ opacity: 0, y: -50, scale: 0.9 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 50, scale: 0.9 }}
        transition={{ type: "spring", damping: 25, stiffness: 300 }}
      >
        <div className="datin-modal-header">
          <h2>Login to DATIN</h2>
          <button className="datin-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="datin-modal-body">
          <form className="datin-form" onSubmit={handleSubmit}>
            <div className="datin-form-group">
              <label htmlFor="email">Email</label>
              <input type="email" id="email" placeholder="Your email address" className="datin-input" required />
            </div>
            <div className="datin-form-group">
              <label htmlFor="password">Password</label>
              <input type="password" id="password" placeholder="Your password" className="datin-input" required />
            </div>
            <div className="datin-form-footer">
              <motion.button 
                type="submit" 
                className="datin-primary datin-form-submit"
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
              >
                Login
              </motion.button>
            </div>
          </form>
          <div className="datin-switch-form">
            <p>Don't have an account? <button onClick={onSwitchToSignup} className="datin-text-button">Sign up</button></p>
          </div>
        </div>
      </motion.div>
    </div>
  );
};

const SignupModal = ({ isOpen, onClose, onSwitchToLogin }) => {
  if (!isOpen) return null;
  
  const handleSubmit = (e) => {
    e.preventDefault();
    console.log('Signup attempted');
  };

  return (
    <div className="datin-modal-overlay" onClick={onClose}>
      <motion.div 
        className="datin-modal" 
        onClick={(e) => e.stopPropagation()}
        initial={{ opacity: 0, y: -50, scale: 0.9 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 50, scale: 0.9 }}
        transition={{ type: "spring", damping: 25, stiffness: 300 }}
      >
        <div className="datin-modal-header">
          <h2>Create Account</h2>
          <button className="datin-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="datin-modal-body">
          <form className="datin-form" onSubmit={handleSubmit}>
            <div className="datin-form-group">
              <label htmlFor="fullname">Full Name</label>
              <input type="text" id="fullname" placeholder="Your full name" className="datin-input" required />
            </div>
            <div className="datin-form-group">
              <label htmlFor="signup-email">Email</label>
              <input type="email" id="signup-email" placeholder="Your email address" className="datin-input" required />
            </div>
            <div className="datin-form-group">
              <label htmlFor="signup-password">Password</label>
              <input type="password" id="signup-password" placeholder="Create a password" className="datin-input" required />
            </div>
            <div className="datin-form-group">
              <label htmlFor="wallet">Wallet Address (Optional)</label>
              <input type="text" id="wallet" placeholder="Your blockchain wallet address" className="datin-input" />
            </div>
            <div className="datin-form-footer">
              <motion.button 
                type="submit" 
                className="datin-primary datin-form-submit"
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
              >
                Create Account
              </motion.button>
            </div>
          </form>
          <div className="datin-switch-form">
            <p>Already have an account? <button onClick={onSwitchToLogin} className="datin-text-button">Login</button></p>
          </div>
        </div>
      </motion.div>
    </div>
  );
};

const Landing = () => {
  const [isLoginOpen, setIsLoginOpen] = useState(false);
  const [isSignupOpen, setIsSignupOpen] = useState(false);
  const navigate = useNavigate();
  
  const featuresRef = useRef(null);
  const { scrollYProgress } = useScroll();
  const featuresControls = useAnimation();
  const featuresScale = useTransform(scrollYProgress, [0, 0.3], [0.8, 1]);
  const featuresOpacity = useTransform(scrollYProgress, [0, 0.3], [0, 1]);
  const titleRef = useRef(null);
  const titleInView = useInView(titleRef, { once: false, amount: 0.5 });

  useEffect(() => {
    if (titleInView) {
      featuresControls.start({
        y: 0,
        opacity: 1,
        transition: { 
          type: "spring", 
          stiffness: 100, 
          damping: 15, 
          delay: 0.2 
        }
      });
    } else {
      featuresControls.start({
        y: 100,
        opacity: 0
      });
    }
  }, [titleInView, featuresControls]);
  
  useEffect(() => {
    if (isLoginOpen || isSignupOpen) {
      document.body.classList.add('modal-open');
    } else {
      document.body.classList.remove('modal-open');
    }
    
    return () => {
      document.body.classList.remove('modal-open');
    };
  }, [isLoginOpen, isSignupOpen]);

  const openLogin = () => {
    setIsLoginOpen(true);
    setIsSignupOpen(false);
  };

  const openSignup = () => {
    setIsSignupOpen(true);
    setIsLoginOpen(false);
  };

  const closeModals = () => {
    setIsLoginOpen(false);
    setIsSignupOpen(false);
  };

  // Navigation handler for "Ask a Query" button
  const handleAskQueryClick = () => {
    navigate('/chat');
  };

  // Navigation handler for "Submit Report" button
  const handleSubmitReportClick = () => {
    navigate('/submit-report');
  };

  // Feature data
  const features = [
    {
      icon: "🔍",
      title: "AI Cybersecurity Assistant",
      description: "Ask any cybersecurity-related question and get instant responses powered by our RAG AI model"
    },
    {
      icon: "📝",
      title: "Decentralized Reports",
      description: "Submit cybersecurity reports to our blockchain network and earn DTNC tokens through verification"
    },
    {
      icon: "⛓️",
      title: "Stake Verification",
      description: "Verify user-submitted reports and earn DTNC tokens for maintaining knowledge integrity"
    },
    {
      icon: "🏢",
      title: "Enterprise Solutions",
      description: "Customizable RAG solutions with your own token rewards and subscription models"
    }
  ];

  return (
    <div className="datin-landing">
      <motion.nav 
        className="datin-nav"
        initial={{ y: -50, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ delay: 0.2, duration: 0.5 }}
      >
        <div className="datin-logo">DATIN</div>
        <ul className="datin-nav-links">
          <li><a href="#features">Features</a></li>
          <li><a href="#how-it-works">How It Works</a></li>
          <li><a href="#enterprise">Enterprise</a></li>
          <li><a href="#contact">Contact</a></li>
        </ul>
        <motion.button 
          className="datin-cta" 
          onClick={openLogin}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
        >
          Login
        </motion.button>
      </motion.nav>

      <section className="datin-hero">
        <motion.div 
          className="datin-hero-content"
          initial={{ opacity: 0, x: -50 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.8 }}
        >
          <TypingAnimation text="Decentralized AI Threat Intelligence Network" />
          <motion.p 
            className="datin-subtitle"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 2, duration: 1 }}
          >
            Get instant AI-powered cybersecurity insights and contribute to our decentralized knowledge base
          </motion.p>
          <motion.div 
            className="datin-hero-buttons"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 2.5, duration: 0.5 }}
          >
            <motion.button 
              className="datin-primary"
              whileHover={{ scale: 1.05, boxShadow: "0 5px 15px rgba(0, 255, 170, 0.4)" }}
              whileTap={{ scale: 0.95 }}
              onClick={handleAskQueryClick}
            >
              Ask a Query
            </motion.button>
            <motion.button 
              className="datin-secondary"
              whileHover={{ scale: 1.05, backgroundColor: "rgba(255, 255, 255, 0.15)" }}
              whileTap={{ scale: 0.95 }}
              onClick={handleSubmitReportClick}
            >
              Submit Report
            </motion.button>
          </motion.div>
        </motion.div>
        <motion.div 
          className="datin-hero-visual"
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.5, duration: 0.8 }}
        >
          <InteractiveCoin />
        </motion.div>
        <motion.div
          style={{ 
            position: "absolute", 
            bottom: "2rem", 
            left: "50%", 
            transform: "translateX(-50%)" 
          }}
        >
          <ScrollDownIndicator />
        </motion.div>
      </section>

      {/* Features Section with Scroll Animation */}
      <motion.section 
        id="features" 
        className="datin-features"
        ref={featuresRef}
        style={{ 
          opacity: featuresOpacity,
          scale: featuresScale,
        }}
      >
        <motion.h2
          ref={titleRef}
          initial={{ y: 50, opacity: 0 }}
          animate={featuresControls}
          className="features-title"
        >
          Core Platform Features
          <motion.div 
            className="title-underline"
            initial={{ width: 0 }}
            animate={titleInView ? { width: "80px" } : { width: 0 }}
            transition={{ delay: 0.5, duration: 0.8 }}
            style={{
              height: "3px",
              background: "linear-gradient(to right, var(--primary), var(--secondary))",
              margin: "0 auto",
              marginTop: "10px"
            }}
          />
        </motion.h2>
        <div className="datin-features-grid">
          {features.map((feature, index) => (
            <FeatureCard 
              key={index}
              icon={feature.icon}
              title={feature.title}
              description={feature.description}
              index={index}
            />
          ))}
        </div>
      </motion.section>

      <section id="how-it-works" className="datin-how-it-works">
        <h2>How DATIN Works</h2>
        <div className="datin-steps">
          <div className="datin-step">
            <div className="datin-step-number">1</div>
            <div className="datin-step-content">
              <h3>Ask or Submit</h3>
              <p>Users can either ask cybersecurity questions to our AI or submit reports with security-related content</p>
            </div>
          </div>
          <div className="datin-step">
            <div className="datin-step-number">2</div>
            <div className="datin-step-content">
              <h3>Blockchain Integration</h3>
              <p>Submitted reports are stored on blockchain with wallet and token address information</p>
            </div>
          </div>
          <div className="datin-step">
            <div className="datin-step-number">3</div>
            <div className="datin-step-content">
              <h3>Community Verification</h3>
              <p>Three random users verify each report's cybersecurity content for accuracy</p>
            </div>
          </div>
          <div className="datin-step">
            <div className="datin-step-number">4</div>
            <div className="datin-step-content">
              <h3>Token Rewards</h3>
              <p>Verified reports reward submitters, and verifiers earn DTNC tokens for their work</p>
            </div>
          </div>
        </div>
      </section>

      <section id="enterprise" className="datin-enterprise">
        <h2>Enterprise Solutions</h2>
        <div className="datin-enterprise-content">
          <div className="datin-enterprise-feature">
            <h3>Custom RAG Models</h3>
            <p>Tailored AI models trained on your specific cybersecurity knowledge base</p>
          </div>
          <div className="datin-enterprise-feature">
            <h3>Private Blockchain</h3>
            <p>Dedicated blockchain network for your internal security reports</p>
          </div>
          <div className="datin-enterprise-feature">
            <h3>Branded Tokens</h3>
            <p>Your own reward token system for employee participation</p>
          </div>
          <div className="datin-enterprise-feature">
            <h3>Flexible Subscription Plans</h3>
            <ul>
              <li>Basic: Query-based access</li>
              <li>Professional: Enhanced features</li>
              <li>Enterprise: Fully customized solutions</li>
            </ul>
          </div>
        </div>
      </section>

      <section className="datin-cta-section">
        <h2>Join the Decentralized Cybersecurity Knowledge Network</h2>
        <p>Start contributing and earning rewards today</p>
        <motion.button 
          className="datin-primary" 
          onClick={openSignup}
          whileHover={{ scale: 1.05, boxShadow: "0 5px 15px rgba(0, 255, 170, 0.4)" }}
          whileTap={{ scale: 0.95 }}
        >
          Sign Up Free
        </motion.button>
      </section>

      <footer className="datin-footer">
        <div className="datin-footer-content">
          <div className="datin-footer-logo">DATIN</div>
          <div className="datin-footer-links">
            <a href="#privacy">Privacy Policy</a>
            <a href="#terms">Terms of Service</a>
            <a href="#docs">Developer API</a>
            <a href="#whitepaper">Whitepaper</a>
          </div>
          <div className="datin-footer-social">
            <a href="#twitter">Twitter</a>
            <a href="#discord">Discord</a>
            <a href="#github">GitHub</a>
          </div>
        </div>
        <div className="datin-footer-copyright">
          © {new Date().getFullYear()} DATIN - Decentralized AI Threat Intelligence Network
        </div>
      </footer>

      <LoginModal 
        isOpen={isLoginOpen} 
        onClose={closeModals} 
        onSwitchToSignup={openSignup} 
      />
      <SignupModal 
        isOpen={isSignupOpen} 
        onClose={closeModals} 
        onSwitchToLogin={openLogin} 
      />
    </div>
  );
};

const App = () => {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/chat" element={<ChatInterface />} />
        <Route path="/submit-report" element={<LogSubmitForm />} />
        <Route path="/dashboard" element={<Landing />} />
      </Routes>
    </Router>
  );
};

export default App;