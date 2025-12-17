from pydantic import BaseModel, Field

class QuoteRequest(BaseModel):
    tenantId: str = Field(..., min_length=1)
    customerMessage: str = Field(..., min_length=1)

    cleanType: str | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    condition: str | None = None
    pets: str | None = None
    addons: list[str] | None = None
    preferredTiming: str | None = None
    notes: str | None = None

class QuoteResponse(BaseModel):
    replyText: str
    lowEstimate: int | None = None
    highEstimate: int | None = None
    includedServices: list[str] = []
    suggestedTimes: list[str] = []
    estimateText: str = ''
    jobSummaryShort: str = ''
    disclaimer: str = 'Prices are estimates and may vary based on condition and access.'