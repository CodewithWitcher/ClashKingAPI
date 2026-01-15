from pydantic import BaseModel, Field, field_validator
from typing import Literal, List, Dict, Any, Union

# Family role types
FamilyRoleType = Literal[
    "family",  # Has at least one account in family
    "not_family",  # Has no accounts in family
    "only_family",  # All accounts are in family
    "family_member",  # Member position in clan
    "family_elder",  # Elder position in clan
    "family_coleader",  # Co-Leader position in clan
    "family_leader",  # Leader position in clan
    "ignored",  # Ignored during auto-eval
]


class FamilyRoleAdd(BaseModel):
    """Add a family role"""
    role: Union[int, str] = Field(..., description="Discord role ID")
    type: FamilyRoleType = Field(..., description="Type of family role")

    @field_validator('role', mode='before')
    @classmethod
    def convert_role_to_int(cls, v):
        """Convert string role ID to int (handles large Discord snowflakes)"""
        return int(v) if isinstance(v, str) else v


class FamilyRoleRemove(BaseModel):
    """Remove a family role"""
    role: Union[int, str] = Field(..., description="Discord role ID")
    type: FamilyRoleType = Field(..., description="Type of family role")

    @field_validator('role', mode='before')
    @classmethod
    def convert_role_to_int(cls, v):
        """Convert string role ID to int (handles large Discord snowflakes)"""
        return int(v) if isinstance(v, str) else v


class FamilyRolesResponse(BaseModel):
    """Response for family roles"""
    server_id: int
    family_roles: List[str] = []  # Has at least one account in family
    not_family_roles: List[str] = []  # Has no accounts in family
    only_family_roles: List[str] = []  # All accounts are in family
    family_member_roles: List[str] = []  # Member position
    family_elder_roles: List[str] = []  # Elder position
    family_coleader_roles: List[str] = []  # Co-Leader position
    family_leader_roles: List[str] = []  # Leader position
    ignored_roles: List[str] = []  # Ignored during auto-eval


class FamilyRoleOperationResponse(BaseModel):
    """Response for family role operations"""
    message: str
    server_id: int
    role_type: str
    role_id: str
