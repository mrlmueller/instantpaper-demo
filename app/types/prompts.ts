export type PromptStage =
  | "process_quelle"
  | "combine"
  | "shorten"
  | "lesefluss"
  | "summary";

export type PromptTemplate = {
  id: string;
  stage: PromptStage;
  name: string;
  instructions: string;
  placeholders: string[];
  createdAt: string;
  updatedAt: string;
};

export type ActivePromptSelections = Partial<Record<PromptStage, string | "default">>;

export type PromptTemplatePayload = {
  stage: PromptStage;
  name: string;
  instructions: string;
};

export type SystemPromptTemplateMeta = {
  stage: PromptStage;
  templateKey: string;
  name: string;
  createdAt: string | null;
  updatedAt: string | null;
};

export type SystemPromptPermissions = {
  canDuplicateSystemPrompts: boolean;
};
