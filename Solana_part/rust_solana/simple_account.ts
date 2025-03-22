import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { SimpleAccount } from "../target/types/simple_account";
import { expect } from "chai";

describe("simple_account", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);

  const program = anchor.workspace.SimpleAccount as Program<SimpleAccount>;
  const authority = anchor.web3.Keypair.generate();
  
  const threatId = "CVE-2023-12345";
  const threatType = 2; // Vulnerability
  const initialSeverity = 4;
  const description = "Critical vulnerability in XYZ library";
  const source = "NIST Database";

  const getThreatPDA = async () => {
    const [pda, _] = await anchor.web3.PublicKey.findProgramAddressSync(
      [
        Buffer.from("threat-intel"),
        authority.publicKey.toBuffer(),
        Buffer.from(threatId)
      ],
      program.programId
    );
    return pda;
  };

  before(async () => {
    // Airdrop SOL to the authority for transaction fees
    const signature = await provider.connection.requestAirdrop(
      authority.publicKey,
      2 * anchor.web3.LAMPORTS_PER_SOL
    );
    await provider.connection.confirmTransaction(signature);
  });

  it("Initializes a threat intelligence record", async () => {
    const threatPDA = await getThreatPDA();
    // Initialize the threat record
    await program.methods
      .initialize(
        threatId,
        threatType,
        initialSeverity,
        description,
        source
      )
      .accounts({
        threatData: threatPDA,
        authority: authority.publicKey,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .signers([authority])
      .rpc();

    // Fetch the created threat record
    const threatRecord = await program.account.threatIntelligence.fetch(threatPDA);
    
    // Verify data fields
    expect(threatRecord.threatId).to.equal(threatId);
    expect(threatRecord.threatType).to.equal(threatType);
    expect(threatRecord.severity).to.equal(initialSeverity);
    expect(threatRecord.description).to.equal(description);
    expect(threatRecord.source).to.equal(source);
    expect(threatRecord.isActive).to.be.true;
    expect(threatRecord.authority.toString()).to.equal(authority.publicKey.toString());
    
    // Verify timestamp
    expect(threatRecord.timestamp.toNumber()).to.be.greaterThan(0);
  });

  it("Updates threat severity", async () => {
    const threatPDA = await getThreatPDA();
    
    // New severity level
    const newSeverity = 5;

    // Update severity
    await program.methods
      .updateSeverity(newSeverity)
      .accounts({
        threatData: threatPDA,
        authority: authority.publicKey,
      })
      .signers([authority])
      .rpc();

    // Fetch the updated threat record
    const updatedThreat = await program.account.threatIntelligence.fetch(threatPDA);
    
    // Verify that severity is updated or not
    expect(updatedThreat.severity).to.equal(newSeverity);
    expect(updatedThreat.lastUpdated.toNumber()).to.be.greaterThan(0);
  });

  it("Deactivates a threat", async () => {
    const threatPDA = await getThreatPDA();

    // Deactivate the threat
    await program.methods
      .deactivate()
      .accounts({
        threatData: threatPDA,
        authority: authority.publicKey,
      })
      .signers([authority])
      .rpc();

    // Fetch the updated threat record
    const updatedThreat = await program.account.threatIntelligence.fetch(threatPDA);
    
    // Verify the threat was deactivated
    expect(updatedThreat.isActive).to.be.false;
  });
});
