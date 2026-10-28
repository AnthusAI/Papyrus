export const useOptionalNewsDeskClient=()=>({shell:{auth:{status:'signedOut',label:'Offline review fixture'},dashboard:{canManageUsers:false}}});
export const loadReferenceAttachmentsForLineageId=async()=>[];
export const loadStoragePathUrl=async()=>{throw new Error('Cloud storage is disconnected in offline review');};
export const loadStoragePathText=async()=>({text:null,error:null});
export const loadModelPayloadsForOwner=async()=>[];
export const uploadModelPayloadForOwner=async()=>({id:"upload"});
export const useAmplifyClient=()=>{throw new Error('Real authentication is disconnected in offline review');};
export const ReaderAuthControl=()=>null;
