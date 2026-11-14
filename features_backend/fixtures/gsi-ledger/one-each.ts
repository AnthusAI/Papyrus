export const schema = {
  Reference: modelWithoutSubscriptions({
      id: a.id().required(),
    })
    .secondaryIndexes((index) => [
      index("feedStateKey").sortKeys(["feedArrivalAt"]).queryField("referencesByFeed"),
      index("tenantId").sortKeys(["createdAt"]).queryField("referencesByTenant"),
    ]),

  Item: modelWithoutSubscriptions({
      id: a.id().required(),
    })
    .secondaryIndexes((index) => [
      index("stage").sortKeys(["updatedAt"]).queryField("itemsByStage"),
      index("tenantId").sortKeys(["createdAt"]).queryField("itemsByTenant"),
    ]),

  CustomThing: a.customType({ x: a.string() }),
}
