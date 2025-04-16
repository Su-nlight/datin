import React, { useRef, useEffect } from 'react';
import './InteractiveCoin.css';

const InteractiveCoin = () => {
  const coinRef = useRef(null);
  const isDragging = useRef(false);
  const previousPosition = useRef({ x: 0 });
  const rotation = useRef({ y: 0 });
  const velocity = useRef(0);
  const animationId = useRef(null);
  const logoUrl = "https://raw.githubusercontent.com/Su-nlight/datin-notfinal/refs/heads/main/Solana_part/meta_data/logo.png";

  const animate = () => {
    if (Math.abs(velocity.current) < 0.1) {
      velocity.current = 0;
      return;
    }

    velocity.current *= 0.96; // Friction
    rotation.current.y += velocity.current;
    coinRef.current.style.transform = `rotateY(${rotation.current.y}deg)`;
    animationId.current = requestAnimationFrame(animate);
  };

  const handleMouseDown = (e) => {
    e.preventDefault();
    isDragging.current = true;
    previousPosition.current.x = e.clientX;
    document.body.style.cursor = 'grabbing';
    cancelAnimationFrame(animationId.current);
  };

  const handleMouseMove = (e) => {
    if (!isDragging.current) return;
    
    const deltaX = e.clientX - previousPosition.current.x;
    velocity.current = deltaX * 0.25;
    rotation.current.y += deltaX * 0.35;
    
    coinRef.current.style.transform = `rotateY(${rotation.current.y}deg)`;
    previousPosition.current.x = e.clientX;
  };

  const handleMouseUp = () => {
    isDragging.current = false;
    document.body.style.cursor = 'grab';
    if (Math.abs(velocity.current) > 0.5) {
      animationId.current = requestAnimationFrame(animate);
    }
  };

  useEffect(() => {
    const coin = coinRef.current;
    
    coin.addEventListener('mousedown', handleMouseDown);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    
    return () => {
      coin.removeEventListener('mousedown', handleMouseDown);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
      cancelAnimationFrame(animationId.current);
    };
  }, []);

  return (
    <div className="coin-container">
      <div className="coin" ref={coinRef}>
        <div className="coin-face coin-front">
          <div className="logo-container">
            <img src={logoUrl} alt="DATIN Logo" className="coin-logo" />
          </div>
          <div className="border-engraving"></div>
        </div>
        <div className="coin-face coin-back">
          <div className="logo-container">
            <img src={logoUrl} alt="DATIN Logo" className="coin-logo" />
          </div>
          <div className="border-engraving"></div>
        </div>
      </div>
    </div>
  );
};

export default InteractiveCoin;