"""Pydantic schemas for the Financial Analytics Dashboard."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MetricCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: float | None = None
    formatted_value: str
    currency: str | None = None
    scale: str | None = None
    period: str | None = None
    yoy_change: float | None = None
    yoy_change_formatted: str | None = None
    yoy_change_unit: str = "%"
    source_citation: str | None = None


class RevenueTrendPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: str
    fiscal_year: str
    revenue: float
    formatted: str
    currency: str | None = None


class ProfitabilityTrendPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: str
    fiscal_year: str
    gross_profit: float | None = None
    net_income: float | None = None
    operating_income: float | None = None
    formatted_gross_profit: str | None = None
    formatted_net_income: str | None = None
    currency: str | None = None


class MarginTrendPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: str
    fiscal_year: str
    gross_profit_margin: float | None = None
    net_profit_margin: float | None = None
    operating_margin: float | None = None


class FinancialSummarySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revenue_performance: str
    profitability: str
    growth: str
    key_observations: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class FinancialDashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    filename: str
    company_name: str | None = None
    currency: str | None = None
    scale: str | None = None
    has_financial_data: bool = False
    message: str | None = None
    available_years: list[str] = Field(default_factory=list)
    kpi_cards: list[MetricCard] = Field(default_factory=list)
    revenue_trend: list[RevenueTrendPoint] = Field(default_factory=list)
    profitability_trend: list[ProfitabilityTrendPoint] = Field(default_factory=list)
    margin_trend: list[MarginTrendPoint] = Field(default_factory=list)
    summary: FinancialSummarySection | None = None
    warnings: list[str] = Field(default_factory=list)
