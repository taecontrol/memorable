export type Persona = {
	name: string;
	filePath: string;
	body: string;
};

// Shape of the custom entry persisted via pi.appendEntry(STATE_TYPE, ...).
export type PersonaStateEntry = {
	type: string;
	customType?: string;
	data?: {
		active?: boolean;
		persona?: Persona;
	};
};
