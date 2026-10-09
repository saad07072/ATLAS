from pydantic import BaseModel, ConfigDict, Field


class GitHubRepository(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=3, max_length=201)
    owner: str = Field(min_length=1, max_length=39)
    private: bool
    html_url: str = Field(min_length=1, max_length=2048)
    description: str | None = None
    default_branch: str | None = None


class GitHubRepositoryList(BaseModel):
    repositories: list[GitHubRepository]
    next_page: int | None = None


class GitHubIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=256)
    body: str | None = None
    state: str = Field(pattern=r"^(open|closed)$")
    html_url: str = Field(min_length=1, max_length=2048)
    user: str = Field(min_length=1, max_length=39)


class GitHubIssueList(BaseModel):
    issues: list[GitHubIssue]
    next_page: int | None = None


class GitHubPullRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=256)
    body: str | None = None
    state: str = Field(pattern=r"^(open|closed)$")
    html_url: str = Field(min_length=1, max_length=2048)
    draft: bool
    merged: bool
    head: str = Field(min_length=1, max_length=255)
    base: str = Field(min_length=1, max_length=255)


class GitHubIssueCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=256)
    html_url: str = Field(min_length=1, max_length=2048)
    state: str = Field(pattern=r"^(open|closed)$")


class GitHubConnectionStatus(BaseModel):
    configured: bool
    connected: bool
