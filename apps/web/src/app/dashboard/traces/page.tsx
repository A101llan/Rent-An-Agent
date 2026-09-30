import React from "react";

export default function TracesPage() {
  return (
    <div className="flex flex-col h-full space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight">Agent Observability</h1>
        <p className="text-muted-foreground">
          View OpenTelemetry traces and logs for your executed agents.
        </p>
      </div>
      
      <div className="flex-1 min-h-[600px] border rounded-lg overflow-hidden bg-white shadow-sm">
        {/* Embed Jaeger UI via iframe. In production, this would be authenticated or proxied. */}
        <iframe 
          src="http://localhost:16686" 
          className="w-full h-full border-0"
          title="Jaeger Traces UI"
        />
      </div>
    </div>
  );
}
