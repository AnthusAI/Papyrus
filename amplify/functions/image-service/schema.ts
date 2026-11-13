import { a } from "@aws-amplify/backend";
import { imageService } from "./resource";
import { functionHandler } from "../../data/function-handler";

const editors = ["editor", "admin"];

/**
 * Core to every site's data API. The one door to the image operations (docs/images.md): `imageRead` runs an
 * operation that only reads, `imageWrite` one that writes or spends. Both admit editors and admins; the function
 * takes who is asking from the verified identity and never from `input`. `requestId` makes a write safe to repeat.
 * `actorKind` may declare the caller an agent, which can only make the call stricter.
 */
export const imageServiceSchemaDefinitions = {
  /**
   * The same door for guidelines (writing, image, video, any registered kind; docs/plans/guidelines-as-data.md). `guidelinesRead` runs an operation that
   * only reads, `guidelinesWrite` one that saves. Both admit editors and admins at the door; the function lets only an admin save, and only a person change
   * a binding constraint. Same arguments, same caller rules, same function and data source as the image fields.
   */
  guidelinesRead: a
    .query()
    .arguments({ op: a.string().required(), input: a.json(), actorKind: a.string() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(editors)])
    .handler(functionHandler("imageService", imageService)),
  guidelinesWrite: a
    .mutation()
    .arguments({ op: a.string().required(), input: a.json(), requestId: a.id().required(), actorKind: a.string() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(editors)])
    .handler(functionHandler("imageService", imageService)),
  imageRead: a
    .query()
    .arguments({ op: a.string().required(), input: a.json(), actorKind: a.string() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(editors)])
    .handler(functionHandler("imageService", imageService)),
  imageWrite: a
    .mutation()
    .arguments({ op: a.string().required(), input: a.json(), requestId: a.id().required(), actorKind: a.string() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(editors)])
    .handler(functionHandler("imageService", imageService)),
};
