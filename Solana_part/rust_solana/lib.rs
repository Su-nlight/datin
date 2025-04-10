use anchor_lang::prelude::*;
use anchor_spl::token::{self, Token, TokenAccount, Transfer};

declare_id!("GzEFpeM1T1gG5msS1GdjxABtpRR1S2Qu8QeLd9WW95wT");

#[derive(Accounts)]
pub struct StakeForVerification<'info> {
    #[account(mut)]
    pub verifier: Signer<'info>,
    #[account(mut)]
    pub verifier_token_account: Account<'info, TokenAccount>,
    #[account(mut)]
    pub stake_vault: Account<'info, TokenAccount>,
    pub token_program: Program<'info, Token>,
}

#[account]
pub struct VerifierStake {
    pub verifier: Pubkey,
    pub journal_entry: Pubkey,
    pub stake_amount: u64,
    pub timestamp: i64,
}

#[account]
pub struct VerificationStake {
    pub verifier: Pubkey,
    pub journal_entry: Pubkey,
    pub stake_amount: u64,
    pub status: VerificationStatus,
    pub timestamp: i64,
    pub slash_amount: Option<u64>,
    pub resolution_time: Option<i64>,
}

#[derive(Clone, AnchorSerialize, AnchorDeserialize, PartialEq)]
pub enum VerificationStatus {
    Staked,
    Verified,
    Disputed,
    Slashed,
}

impl VerificationStake {
    pub const SIZE: usize = 32 + // verifier
        32 + // journal_entry
        8 +  // stake_amount
        1 +  // status
         8 +  // timestamp
        9 +  // slash_amount (Option<u64>)
        9;   // resolution_time (Option<i64>)
}

#[program]
pub mod datin {
    use super::*;

    // Initialize a new journal entry
    pub fn create_journal_entry(
        ctx: Context<CreateJournalEntry>,
        content: String,
        required_verifier_count: u8,
        reward_per_verifier: u64,
    ) -> Result<()> {
        require!(required_verifier_count >= 3, ErrorCode::InsufficientVerifiers);
        
        let journal_entry = &mut ctx.accounts.journal_entry;
        let owner = &ctx.accounts.owner;
        let clock = Clock::get()?;

        // Calculate total reward needed
        let total_reward = (required_verifier_count as u64)
            .checked_mul(reward_per_verifier)
            .ok_or(ErrorCode::CalculationError)?;

        // Verify owner has enough tokens
        require!(
            ctx.accounts.owner_token_account.amount >= total_reward,
            ErrorCode::InsufficientFunds
        );

        journal_entry.owner = owner.key();
        journal_entry.content = content;
        journal_entry.timestamp = clock.unix_timestamp;
        journal_entry.verified = false;
        journal_entry.immutable = false;
        journal_entry.token_address = ctx.accounts.token_mint.key();
        journal_entry.required_verifier_count = required_verifier_count;
        journal_entry.reward_per_verifier = reward_per_verifier;
        journal_entry.current_verifier_count = 0;

        Ok(())
    }

    // Edit an unverified journal entry
    pub fn edit_journal_entry(
        ctx: Context<EditJournalEntry>,
        new_content: String,
    ) -> Result<()> {
        let journal_entry = &mut ctx.accounts.journal_entry;
        
        require!(!journal_entry.verified, ErrorCode::EntryAlreadyVerified);
        require!(!journal_entry.immutable, ErrorCode::EntryIsImmutable);
        
        journal_entry.content = new_content;
        Ok(())
    }

    // Delete an unverified journal entry
    pub fn delete_journal_entry(ctx: Context<DeleteJournalEntry>) -> Result<()> {
        let journal_entry = &ctx.accounts.journal_entry;
        
        require!(!journal_entry.verified, ErrorCode::EntryAlreadyVerified);
        require!(!journal_entry.immutable, ErrorCode::EntryIsImmutable);
        
        // The account will be closed and rent will be returned to the owner
        Ok(())
    }

    pub fn verify_entry(
        ctx: Context<VerifyEntry>, 
        stake_amount: u64
    ) -> Result<()> {
        let journal_entry = &mut ctx.accounts.journal_entry;
        let verifier = &ctx.accounts.verifier;
        let clock = Clock::get()?;

        // Validation checks
        require!(!journal_entry.verified, ErrorCode::EntryAlreadyVerified);
        require!(stake_amount > 0, ErrorCode::InvalidStakeAmount);
        require!(
            journal_entry.current_verifier_count < journal_entry.required_verifier_count,
            ErrorCode::MaxVerifiersReached
        );

        // Transfer stake to verification vault
        token::transfer(
            CpiContext::new(
                ctx.accounts.token_program.to_account_info(),
                Transfer {
                    from: ctx.accounts.verifier_token_account.to_account_info(),
                    to: ctx.accounts.stake_vault.to_account_info(),
                    authority: verifier.to_account_info(),
                }
            ),
            stake_amount
        )?;

        // Create verification stake account
        let verification_stake = &mut ctx.accounts.verification_stake;
        verification_stake.verifier = verifier.key();
        verification_stake.journal_entry = journal_entry.key();
        verification_stake.stake_amount = stake_amount;
        verification_stake.status = VerificationStatus::Staked;
        verification_stake.timestamp = clock.unix_timestamp;

        // Update journal entry verification count
        journal_entry.current_verifier_count = journal_entry.current_verifier_count
            .checked_add(1)
            .ok_or(ErrorCode::CalculationError)?;

        // Check if entry should be marked as verified
        if journal_entry.current_verifier_count >= journal_entry.required_verifier_count {
            journal_entry.verified = true;
            journal_entry.immutable = true;
        }

        Ok(())
    }

    pub fn resolve_dispute(
        ctx: Context<ResolveDispute>,
        is_verifier_honest: bool,
        slash_percentage: u8,
    ) -> Result<()> {
        let verification_stake = &mut ctx.accounts.verification_stake;
        let dispute_record = &mut ctx.accounts.dispute_record;
        let clock = Clock::get()?;

        require!(
            verification_stake.status == VerificationStatus::Disputed,
            ErrorCode::InvalidDisputeResolution
        );

        require!(
            slash_percentage <= 100,
            ErrorCode::InvalidStakeAmount
        );

        require!(
            clock.unix_timestamp - dispute_record.creation_time <= 7 * 24 * 60 * 60,
            ErrorCode::DisputePeriodExpired
        );

        if !is_verifier_honest {
            let slash_amount = (verification_stake.stake_amount as u128)
                .checked_mul(slash_percentage as u128)
                .and_then(|r| r.checked_div(100))
                .and_then(|r| u64::try_from(r).ok())
                .ok_or(ErrorCode::CalculationError)?;

            verification_stake.status = VerificationStatus::Slashed;
            verification_stake.slash_amount = Some(slash_amount);
            verification_stake.resolution_time = Some(clock.unix_timestamp);

            token::transfer(
                CpiContext::new(
                    ctx.accounts.token_program.to_account_info(),
                    Transfer {
                        from: ctx.accounts.stake_vault.to_account_info(),
                        to: ctx.accounts.penalty_vault.to_account_info(),
                        authority: ctx.accounts.authority.to_account_info(),
                    }
                ),
                slash_amount
            )?;

            dispute_record.status = DisputeStatus::Resolved;
            dispute_record.resolution_time = Some(clock.unix_timestamp);
        } else {
            verification_stake.status = VerificationStatus::Verified;
            verification_stake.resolution_time = Some(clock.unix_timestamp);
            dispute_record.status = DisputeStatus::Rejected;
            dispute_record.resolution_time = Some(clock.unix_timestamp);
        }

        Ok(())
    }

    pub fn stake_for_verification(ctx: Context<StakeForVerification>, amount: u64) -> Result<()> {
        // Transfer tokens from verifier to stake vault
        let cpi_accounts = Transfer {
            from: ctx.accounts.verifier_token_account.to_account_info(),
            to: ctx.accounts.stake_vault.to_account_info(),
            authority: ctx.accounts.verifier.to_account_info(),
        };
        let cpi_program = ctx.accounts.token_program.to_account_info();
        let cpi_ctx = CpiContext::new(cpi_program, cpi_accounts);
        token::transfer(cpi_ctx, amount)?;

        Ok(())
    }

    pub fn distribute_rewards(
        ctx: Context<DistributeRewards>,
    ) -> Result<()> {
        let journal_entry = &mut ctx.accounts.journal_entry;
        require!(journal_entry.verified, ErrorCode::EntryNotVerified);

        // Transfer rewards from journal entry to verifier
        let amount = journal_entry.reward_per_verifier;
        
        token::transfer(
            CpiContext::new(
                ctx.accounts.token_program.to_account_info(),
                token::Transfer {
                    from: ctx.accounts.user_token_account.to_account_info(),
                    to: ctx.accounts.verifier_token_account.to_account_info(),
                    authority: ctx.accounts.user.to_account_info(),
                },
            ),
            amount,
        )?;

        Ok(())
    }

    pub fn create_dispute(
        ctx: Context<DisputeVerification>,
    ) -> Result<()> {
        let verification_stake = &mut ctx.accounts.verification_stake;

        require!(
            verification_stake.status == VerificationStatus::Staked,
            ErrorCode::DisputeAlreadyExists
        );

        verification_stake.status = VerificationStatus::Disputed;
        Ok(())
    }
}

#[derive(Accounts)]
#[instruction(content: String)]
pub struct CreateJournalEntry<'info> {
    #[account(init, payer = owner, space = 8 + JournalEntry::SIZE)]
    pub journal_entry: Account<'info, JournalEntry>,
    #[account(mut)]
    pub owner: Signer<'info>,
    pub token_mint: Account<'info, token::Mint>,
    #[account(
        mut,
        constraint = owner_token_account.owner == owner.key(),
        constraint = owner_token_account.mint == token_mint.key()
    )]
    pub owner_token_account: Account<'info, TokenAccount>,
    pub system_program: Program<'info, System>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct EditJournalEntry<'info> {
    #[account(
        mut,
        constraint = journal_entry.owner == owner.key()
    )]
    pub journal_entry: Account<'info, JournalEntry>,
    pub owner: Signer<'info>,
}

#[derive(Accounts)]
pub struct DeleteJournalEntry<'info> {
    #[account(
        mut,
        constraint = journal_entry.owner == owner.key(),
        close = owner
    )]
    pub journal_entry: Account<'info, JournalEntry>,
    pub owner: Signer<'info>,
}

#[derive(Accounts)]
#[instruction(stake_amount: u64)]
pub struct VerifyEntry<'info> {
    #[account(mut)]
    pub journal_entry: Account<'info, JournalEntry>,
    #[account(mut)]
    pub verifier: Signer<'info>,
    #[account(mut)]
    pub verifier_token_account: Account<'info, TokenAccount>,
    #[account(mut)]
    pub stake_vault: Account<'info, TokenAccount>,
    #[account(init, payer = verifier, space = 8 + VerificationStake::SIZE)]
    pub verification_stake: Account<'info, VerificationStake>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct DistributeRewards<'info> {
    #[account(mut)]
    pub user: Signer<'info>,
    
    #[account(
        mut,
        seeds = [b"journal", journal_entry.owner.as_ref(), &journal_entry.timestamp.to_be_bytes()],
        bump = journal_entry.bump,
        constraint = journal_entry.owner == user.key() @ ErrorCode::Unauthorized,
        constraint = journal_entry.verified @ ErrorCode::EntryNotVerified
    )]
    pub journal_entry: Account<'info, JournalEntry>,
    
    #[account(mut)]
    pub user_token_account: Account<'info, TokenAccount>,
    
    #[account(mut)]
    pub verifier_token_account: Account<'info, TokenAccount>,
    
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct DisputeVerification<'info> {
    #[account(mut)]
    pub verification_stake: Account<'info, VerificationStake>,
    #[account(mut)]
    pub journal_entry: Account<'info, JournalEntry>,
    pub disputer: Signer<'info>,
}

#[derive(Accounts)]
pub struct ResolveDispute<'info> {
    #[account(
        mut,
        constraint = verification_stake.status == VerificationStatus::Disputed
    )]
    pub verification_stake: Account<'info, VerificationStake>,
    #[account(mut)]
    pub dispute_record: Account<'info, DisputeRecord>,
    #[account(mut)]
    pub stake_vault: Account<'info, TokenAccount>,
    #[account(mut)]
    pub penalty_vault: Account<'info, TokenAccount>,
    pub authority: Signer<'info>,
    pub token_program: Program<'info, Token>,
}

#[account]
pub struct JournalEntry {
    pub owner: Pubkey,
    pub content: String,
    pub timestamp: i64,
    pub verified: bool,
    pub immutable: bool,
    pub token_address: Pubkey,
    pub required_verifier_count: u8,
    pub current_verifier_count: u8,
    pub reward_per_verifier: u64,
    pub bump: u8,
}

impl JournalEntry {
    pub const SIZE: usize = 32 + // owner
        4 + 1024 + // content (String with max 1024 bytes)
        8 + // timestamp
        1 + // verified
        1 + // immutable
        32 + // token_address
        1 + // required_verifier_count
        1 + // current_verifier_count
        8 + // reward_per_verifier
        1; // bump
}

#[account]
pub struct DisputeRecord {
    pub journal_entry: Pubkey,
    pub verification_stake: Pubkey,
    pub disputer: Pubkey,
    pub evidence_hash: [u8; 32],
    pub creation_time: i64,
    pub resolution_time: Option<i64>,
    pub status: DisputeStatus,
    pub bump: u8,
}

#[derive(Clone, AnchorSerialize, AnchorDeserialize, PartialEq)]
pub enum DisputeStatus {
    Pending,
    Resolved,
    Rejected,
}

impl DisputeRecord {
    pub const SIZE: usize = 32 + // journal_entry
        32 + // verification_stake
        32 + // disputer
        32 + // evidence_hash
        8 +  // creation_time
        9 +  // resolution_time (Option<i64>)
        1 +  // status
        1;   // bump
}

#[error_code]
pub enum ErrorCode {
    #[msg("Insufficient verifiers specified (minimum 3 required)")]
    InsufficientVerifiers,
    #[msg("Entry is already verified")]
    EntryAlreadyVerified,
    #[msg("Entry is immutable")]
    EntryIsImmutable,
    #[msg("Maximum verifiers reached")]
    MaxVerifiersReached,
    #[msg("Calculation error")]
    CalculationError,
    #[msg("Insufficient funds for rewards")]
    InsufficientFunds,
    #[msg("Invalid stake amount")]
    InvalidStakeAmount,
    #[msg("Entry not verified")]
    EntryNotVerified,
    #[msg("Verifier already staked")]
    VerifierAlreadyStaked,
    #[msg("Insufficient stake")]
    InsufficientStake,
    #[msg("Unauthorized action")]
    Unauthorized,
    #[msg("Dispute raised against verification")]
    VerificationDisputed,
    #[msg("Invalid dispute resolution")]
    InvalidDisputeResolution,
    #[msg("Dispute already exists for this verification")]
    DisputeAlreadyExists,
    #[msg("Dispute period expired")]
    DisputePeriodExpired,
    #[msg("Invalid dispute evidence")]
    InvalidDisputeEvidence,
    #[msg("Dispute resolution in progress")]
    DisputeInProgress,
    #[msg("Invalid resolution authority")]
    InvalidResolutionAuthority,
}
