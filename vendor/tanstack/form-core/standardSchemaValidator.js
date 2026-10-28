function prefixSchemaToErrors(issues) {
  const schema = /* @__PURE__ */ new Map();
  for (const issue of issues) {
    const path = [...issue.path ?? []].map((segment) => {
      const normalizedSegment = typeof segment === "object" ? segment.key : segment;
      return typeof normalizedSegment === "number" ? `[${normalizedSegment}]` : normalizedSegment;
    }).join(".").replace(/\.\[/g, "[");
    schema.set(path, (schema.get(path) ?? []).concat(issue));
  }
  return Object.fromEntries(schema);
}
const defaultFieldTransformer = (issues) => issues;
const defaultFormTransformer = (issues) => {
  const schemaErrors = prefixSchemaToErrors(issues);
  return {
    form: schemaErrors,
    fields: schemaErrors
  };
};
const transformIssues = (validationSource, issues) => validationSource === "form" ? defaultFormTransformer(issues) : defaultFieldTransformer(issues);
const standardSchemaValidators = {
  validate({ value, validationSource }, schema) {
    const result = schema["~standard"].validate(value);
    if (result instanceof Promise) {
      throw new Error("async function passed to sync validator");
    }
    if (!result.issues) return;
    return transformIssues(validationSource, result.issues);
  },
  async validateAsync({ value, validationSource }, schema) {
    const result = await schema["~standard"].validate(value);
    if (!result.issues) return;
    return transformIssues(validationSource, result.issues);
  }
};
const isStandardSchemaValidator = (validator) => !!validator && "~standard" in validator;
export {
  isStandardSchemaValidator,
  standardSchemaValidators
};
