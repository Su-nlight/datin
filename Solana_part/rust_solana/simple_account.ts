import * as anchor from '@coral-xyz/anchor';
import { Program } from '@coral-xyz/anchor';
import { Datin } from '../target/types/datin';
import { 
    TOKEN_PROGRAM_ID,
    getOrCreateAssociatedTokenAccount,
    createMint,
    mintTo,
    getAccount
} from "@solana/spl-token";
import { expect } from "chai";
import { ensureMinimumBalance } from './utils/test-helpers';

const VerificationStatus = {
  Staked: { staked: {} },
  Verified: { verified: {} },
  Disputed: { disputed: {} },
  Slashed: { slashed: {} }
};

const DisputeStatus = {
  Pending: { pending: {} },
  Resolved: { resolved: {} },
  Rejected: { rejected: {} }
};

async function getTokenBalance(connection: anchor.web3.Connection, account: anchor.web3.PublicKey): Promise<number> {
    const balance = await connection.getTokenAccountBalance(account);
    return Number(balance.value.amount);
}

describe("Verification Process", () => {
    const provider = anchor.AnchorProvider.env();
    anchor.setProvider(provider);

    const program = anchor.workspace.Datin as Program<Datin>;
    let tokenMint: anchor.web3.PublicKey;
    let ownerTokenAccount: any;
    let stakeVault: any;
    let verifierTokenAccount: any;
    let penaltyVault: any;
    let mintAuthority: anchor.web3.Keypair;
    let journalEntry: anchor.web3.Keypair;
    let verificationStake: anchor.web3.Keypair;

    before(async function() {
        this.timeout(120000);

        try {
            await ensureMinimumBalance(
                provider.connection,
                provider.wallet.publicKey
            );

            mintAuthority = anchor.web3.Keypair.generate();
            await ensureMinimumBalance(
                provider.connection,
                mintAuthority.publicKey
            );

            tokenMint = await createMint(
                provider.connection,
                provider.wallet.payer,
                mintAuthority.publicKey,
                mintAuthority.publicKey,
                9
            );

            ownerTokenAccount = await getOrCreateAssociatedTokenAccount(
                provider.connection,
                provider.wallet.payer,
                tokenMint,
                provider.wallet.publicKey
            );

            stakeVault = await getOrCreateAssociatedTokenAccount(
                provider.connection,
                provider.wallet.payer,
                tokenMint,
                program.programId
            );

            penaltyVault = await getOrCreateAssociatedTokenAccount(
                provider.connection,
                provider.wallet.payer,
                tokenMint,
                program.programId
            );

            verifierTokenAccount = await getOrCreateAssociatedTokenAccount(
                provider.connection,
                provider.wallet.payer,
                tokenMint,
                provider.wallet.publicKey
            );

            await mintTo(
                provider.connection,
                provider.wallet.payer,
                tokenMint,
                ownerTokenAccount.address,
                mintAuthority,
                1_000_000_000_000
            );

            await mintTo(
                provider.connection,
                provider.wallet.payer,
                tokenMint,
                verifierTokenAccount.address,
                mintAuthority,
                1_000_000_000_000
            );

            journalEntry = anchor.web3.Keypair.generate();
            verificationStake = anchor.web3.Keypair.generate();

        } catch (error) {
            console.error('Setup failed:', error);
            throw error;
        }
    });

    it("Verifies journal entry with stake", async () => {
        const journalEntry = anchor.web3.Keypair.generate();
        const verificationStake = anchor.web3.Keypair.generate();

        await program.methods
            .createJournalEntry(
                "Test Entry",
                3, // required_verifier_count
                new anchor.BN(100) // reward_per_verifier
            )
            .accounts({
                journalEntry: journalEntry.publicKey,
                owner: provider.wallet.publicKey,
                tokenMint,
                ownerTokenAccount: ownerTokenAccount.address,
                systemProgram: anchor.web3.SystemProgram.programId,
                tokenProgram: TOKEN_PROGRAM_ID,
            })
            .signers([journalEntry])
            .rpc();

        await program.methods
            .verifyEntry(new anchor.BN(100))
            .accounts({
                journalEntry: journalEntry.publicKey,
                verifier: provider.wallet.publicKey,
                verifierTokenAccount: verifierTokenAccount.address,
                stakeVault: stakeVault.address,
                verificationStake: verificationStake.publicKey,
                tokenProgram: TOKEN_PROGRAM_ID,
                systemProgram: anchor.web3.SystemProgram.programId,
            })
            .signers([verificationStake])
            .rpc();

        const journalAccountData = await program.account.journalEntry.fetch(journalEntry.publicKey);
        expect(journalAccountData.currentVerifierCount).to.equal(1);
    });

    it("Handles verification disputes", async () => {
        const journalEntry = anchor.web3.Keypair.generate();
        const verificationStake = anchor.web3.Keypair.generate();
        const disputeRecord = anchor.web3.Keypair.generate();

        await program.methods
            .createJournalEntry(
                "Test Entry for Dispute",
                3, // required_verifier_count
                new anchor.BN(100) // reward_per_verifier
            )
            .accounts({
                journalEntry: journalEntry.publicKey,
                owner: provider.wallet.publicKey,
                tokenMint,
                ownerTokenAccount: ownerTokenAccount.address,
                systemProgram: anchor.web3.SystemProgram.programId,
                tokenProgram: TOKEN_PROGRAM_ID,
            })
            .signers([journalEntry])
            .rpc();

        await program.methods
            .verifyEntry(new anchor.BN(100))
            .accounts({
                journalEntry: journalEntry.publicKey,
                verifier: provider.wallet.publicKey,
                verifierTokenAccount: verifierTokenAccount.address,
                stakeVault: stakeVault.address,
                verificationStake: verificationStake.publicKey,
                tokenProgram: TOKEN_PROGRAM_ID,
                systemProgram: anchor.web3.SystemProgram.programId,
            })
            .signers([verificationStake])
            .rpc();

        await program.methods
            .createDispute()
            .accounts({
                verificationStake: verificationStake.publicKey,
                journalEntry: journalEntry.publicKey,
                disputer: provider.wallet.publicKey,
            })
            .rpc();

        const verificationStakeData = await program.account.verificationStake.fetch(
            verificationStake.publicKey
        );
        expect(verificationStakeData.status).to.deep.equal(VerificationStatus.Disputed);
    });

    it("Handles complete dispute resolution process", async () => {
        const journalEntry = anchor.web3.Keypair.generate();
        const verificationStake = anchor.web3.Keypair.generate();
        const disputeRecord = anchor.web3.Keypair.generate();

        const initialStakeVaultBalance = await getTokenBalance(
            provider.connection,
            stakeVault.address
        );

        await program.methods
            .createJournalEntry(
                "Test content for dispute",
                3, // required verifiers
                new anchor.BN(1000000) // 1 token reward per verifier
            )
            .accounts({
                journalEntry: journalEntry.publicKey,
                owner: provider.wallet.publicKey,
                tokenMint: tokenMint,
                ownerTokenAccount: ownerTokenAccount.address,
                systemProgram: anchor.web3.SystemProgram.programId,
                tokenProgram: TOKEN_PROGRAM_ID,
            })
            .signers([journalEntry])
            .rpc();

        try {
            const stakeAmount = new anchor.BN(5000000);
            await program.methods
                .verifyEntry(stakeAmount)
                .accounts({
                    journalEntry: journalEntry.publicKey,
                    verifier: provider.wallet.publicKey,
                    verifierTokenAccount: verifierTokenAccount.address,
                    stakeVault: stakeVault.address,
                    verificationStake: verificationStake.publicKey,
                    tokenProgram: TOKEN_PROGRAM_ID,
                    systemProgram: anchor.web3.SystemProgram.programId,
                })
                .signers([verificationStake])
                .rpc();

            const stakeVaultBalance = await getTokenBalance(
                provider.connection,
                stakeVault.address
            );
            expect(stakeVaultBalance - initialStakeVaultBalance).to.equal(5000000);
        } catch (error) {
            console.error("Staking failed:", error);
            throw error;
        }

        try {
            await program.methods
                .createDispute()
                .accounts({
                    verificationStake: verificationStake.publicKey,
                    journalEntry: journalEntry.publicKey,
                    disputer: provider.wallet.publicKey,
                })
                .rpc();

            const verificationStakeData = await program.account.verificationStake.fetch(
                verificationStake.publicKey
            );
            expect(verificationStakeData.status).to.deep.equal(VerificationStatus.Disputed);
        } catch (error) {
            console.error("Dispute creation failed:", error);
            throw error;
        }

        // TODO: Add dispute resolution test here once DisputeRecord is implemented
        console.log("Skipping resolution test - needs DisputeRecord implementation");
    });

    it("Prevents duplicate disputes", async () => {
        const journalEntry = anchor.web3.Keypair.generate();
        const verificationStake = anchor.web3.Keypair.generate();

        await program.methods
            .createJournalEntry(
                "Test Entry for Duplicate Dispute",
                3, // required_verifier_count
                new anchor.BN(100) // reward_per_verifier
            )
            .accounts({
                journalEntry: journalEntry.publicKey,
                owner: provider.wallet.publicKey,
                tokenMint,
                ownerTokenAccount: ownerTokenAccount.address,
                systemProgram: anchor.web3.SystemProgram.programId,
                tokenProgram: TOKEN_PROGRAM_ID,
            })
            .signers([journalEntry])
            .rpc();

        await program.methods
            .verifyEntry(new anchor.BN(100))
            .accounts({
                journalEntry: journalEntry.publicKey,
                verifier: provider.wallet.publicKey,
                verifierTokenAccount: verifierTokenAccount.address,
                stakeVault: stakeVault.address,
                verificationStake: verificationStake.publicKey,
                tokenProgram: TOKEN_PROGRAM_ID,
                systemProgram: anchor.web3.SystemProgram.programId,
            })
            .signers([verificationStake])
            .rpc();
        
        await program.methods
            .createDispute()
            .accounts({
                verificationStake: verificationStake.publicKey,
                journalEntry: journalEntry.publicKey,
                disputer: provider.wallet.publicKey,
            })
            .rpc();

        try {
            await program.methods
                .createDispute()
                .accounts({
                    verificationStake: verificationStake.publicKey,
                    journalEntry: journalEntry.publicKey,
                    disputer: provider.wallet.publicKey,
                })
                .rpc();
            expect.fail("Should not allow duplicate disputes");
        } catch (error) {
            expect(error.message).to.include("Error");
        }
    });

    it("Stakes for verification", async () => {
        const journalEntry = anchor.web3.Keypair.generate();
        const verificationStake = anchor.web3.Keypair.generate();
        const stakeAmount = new anchor.BN(100);
        
        await program.methods
            .createJournalEntry(
                "Test Entry for Staking",
                3, // required_verifier_count
                new anchor.BN(100) // reward_per_verifier
            )
            .accounts({
                journalEntry: journalEntry.publicKey,
                owner: provider.wallet.publicKey,
                tokenMint,
                ownerTokenAccount: ownerTokenAccount.address,
                systemProgram: anchor.web3.SystemProgram.programId,
                tokenProgram: TOKEN_PROGRAM_ID,
            })
            .signers([journalEntry])
            .rpc();
        
        await program.methods
            .verifyEntry(stakeAmount)
            .accounts({
                journalEntry: journalEntry.publicKey,
                verifier: provider.wallet.publicKey,
                verifierTokenAccount: verifierTokenAccount.address,
                stakeVault: stakeVault.address,
                verificationStake: verificationStake.publicKey,
                tokenProgram: TOKEN_PROGRAM_ID,
                systemProgram: anchor.web3.SystemProgram.programId,
            })
            .signers([verificationStake])
            .rpc();

        const stakeVaultBalance = await provider.connection.getTokenAccountBalance(stakeVault.address);
        console.log("Stake vault balance:", stakeVaultBalance.value.uiAmount);
        
        const verificationStakeData = await program.account.verificationStake.fetch(
            verificationStake.publicKey
        );
        expect(verificationStakeData.verifier.toString()).to.equal(provider.wallet.publicKey.toString());
        expect(verificationStakeData.journalEntry.toString()).to.equal(journalEntry.publicKey.toString());
        expect(verificationStakeData.stakeAmount.toNumber()).to.equal(stakeAmount.toNumber());
        expect(verificationStakeData.status).to.deep.equal(VerificationStatus.Staked);
    });
});
