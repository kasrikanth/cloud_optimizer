from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResourceInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=160, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:/-]*$')
    name: str = Field(min_length=1, max_length=160)
    provider: Literal['Azure', 'AWS', 'GCP']
    accountId: str | None = Field(default=None, min_length=1, max_length=36, pattern=r'^[A-Za-z0-9][A-Za-z0-9-]*$')
    region: str = Field(min_length=1, max_length=160)
    type: str = Field(min_length=1, max_length=160)
    env: Literal['Development', 'Staging', 'Production']
    owner: str = Field(min_length=1, max_length=160)
    cost: float = Field(ge=0, le=10_000_000)
    targetCost: float = Field(ge=0, le=10_000_000)
    cpu: float = Field(ge=0, le=100)
    memory: float | None = Field(ge=0, le=100)
    network: float = Field(ge=0, le=10_000_000)
    days: int = Field(ge=0, le=3650)
    coverage: float = Field(ge=0, le=100)
    hours: float = Field(ge=0, le=744)
    critical: bool = Field(strict=True)


class InventoryInput(BaseModel):
    resources: list[ResourceInput] = Field(min_length=1, max_length=500)
    replace: bool = False

    @model_validator(mode='after')
    def no_duplicates(self):
        ids = [r.id for r in self.resources]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate resource IDs are not allowed')
        return self


class DecisionInput(BaseModel):
    action: Literal['approve', 'dismiss', 'reopen', 'simulate', 'implement']
    expected_version: int = Field(ge=1)
    expected_generation: str = Field(min_length=36, max_length=36)
    reviewer: str = Field(default='', max_length=80)


class SeedInput(BaseModel):
    replace: bool = False


EMAIL_PATTERN = r'^[^@\s]+@[^@\s]+\.[^@\s]+$'


class LoginInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(min_length=3, max_length=160, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=1, max_length=200)


class SignupInput(LoginInput):
    organization: str = Field(min_length=2, max_length=80)
    name: str = Field(default='', max_length=80)


class MemberInput(LoginInput):
    name: str = Field(default='', max_length=80)
    role: Literal['admin', 'member'] = 'member'


class AccountInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=80)
    provider: Literal['Azure', 'AWS', 'GCP']
    account_ref: str = Field(min_length=3, max_length=100, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:/-]*$')
    region: str = Field(default='', max_length=60)
    mode: Literal['demo', 'aws', 'azure', 'aws_emu', 'azure_emu', 'import'] = 'import'
    credentials: dict[str, str] | None = None
    budget_usd: float | None = Field(default=None, ge=0, le=100_000_000)


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=2, max_length=80)
    budget_usd: float | None = Field(default=None, ge=0, le=100_000_000)
    credentials: dict[str, str] | None = None


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=80)


class AskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=300)
