use anchor_lang::prelude::*;

declare_id!("7qeWxi89kUaK2McEWNHBdVAGtp3JXQCwd88Wxwg1hQGd");

#[program]
pub mod simple_account {
    use super::*;

    pub fn initialize(
        ctx: Context<Initialize>,
        threat_id: String,
        threat_type: u8,
        severity: u8,
        description: String,
        source: String,
    ) -> Result<()> {
        let threat = &mut ctx.accounts.threat_data;
        
        require!(threat_id.len() <= 32, ErrorCode::ThreatIdTooLong);
        require!(description.len() <= 200, ErrorCode::DescriptionTooLong);
        require!(source.len() <= 50, ErrorCode::SourceTooLong);
        require!(severity <= 5, ErrorCode::InvalidSeverity);
        require!(threat_type <= 5, ErrorCode::InvalidThreatType);
        
        threat.threat_id = threat_id;
        threat.threat_type = threat_type;
        threat.severity = severity;
        threat.timestamp = Clock::get()?.unix_timestamp;
        threat.description = description;
        threat.source = source;
        threat.is_active = true;
        threat.authority = *ctx.accounts.authority.key;

        msg!("Threat intelligence record created: {}", threat.threat_id);
        Ok(())
    }

    pub fn update_severity(ctx: Context<UpdateThreat>, new_severity: u8) -> Result<()> {
        require!(new_severity <= 5, ErrorCode::InvalidSeverity);
        
        let threat = &mut ctx.accounts.threat_data;
        let old_severity = threat.severity;
        threat.severity = new_severity;
        threat.last_updated = Clock::get()?.unix_timestamp;
        
        msg!("Threat severity updated from {} to {}", old_severity, new_severity);
        Ok(())
    }

    pub fn deactivate(ctx: Context<UpdateThreat>) -> Result<()> {
        let threat = &mut ctx.accounts.threat_data;
        threat.is_active = false;
        threat.last_updated = Clock::get()?.unix_timestamp;
        
        msg!("Threat deactivated: {}", threat.threat_id);
        Ok(())
    }
}

#[derive(Accounts)]
#[instruction(threat_id: String)]
pub struct Initialize<'info> {
    #[account(
        init,
        payer = authority,
        space = 8 +                        
                32 +                       
                1 +                        
                1 +                        
                8 +                       
                8 +                       
                4 + 200 +                  
                4 + 50 +                   
                1 +                        
                32,                        
        seeds = [b"threat-intel", authority.key().as_ref(), threat_id.as_bytes()],
        bump
    )]
    pub threat_data: Account<'info, ThreatIntelligence>,
    
    #[account(mut)]
    pub authority: Signer<'info>,
    
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct UpdateThreat<'info> {
    #[account(
        mut,
        seeds = [b"threat-intel", authority.key().as_ref(), threat_data.threat_id.as_bytes()],
        bump,
        has_one = authority
    )]
    pub threat_data: Account<'info, ThreatIntelligence>,
    
    pub authority: Signer<'info>,
}

#[account]
pub struct ThreatIntelligence {
    pub threat_id: String,        
    pub threat_type: u8,          
    pub severity: u8,             
    pub timestamp: i64,           
    pub last_updated: i64,        
    pub description: String,     
    pub source: String,           
    pub is_active: bool,          
    pub authority: Pubkey,        
}

#[error_code]
pub enum ErrorCode {
    #[msg("Threat ID cannot exceed 32 characters")]
    ThreatIdTooLong,
    #[msg("Description cannot exceed 200 characters")]
    DescriptionTooLong,
    #[msg("Source cannot exceed 50 characters")]
    SourceTooLong,
    #[msg("Severity must be between 0 and 5")]
    InvalidSeverity,
    #[msg("Threat type must be between 0 and 5")]
    InvalidThreatType,
}
