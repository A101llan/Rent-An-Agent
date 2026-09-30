export class ExecutionContext {
  public sessionId: string;
  public permissions: string[];

  constructor(sessionId: string, permissions: string[]) {
    this.sessionId = sessionId;
    this.permissions = permissions;
  }

  public hasPermission(permission: string): boolean {
    return this.permissions.includes(permission);
  }
}

export abstract class Agent {
  /**
   * Execute the agent with the given request and session context.
   */
  abstract run(request: Record<string, any>, context: ExecutionContext): Promise<Record<string, any>>;
}
